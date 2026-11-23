"""PS-06: local, per-presentation build profiles.

Profiles are separate from source documents and from the installed style registry.
A saved profile records a *pinned* style and the exact registry manifest digest,
not a mutable theme name. It does not execute renderers or contact any service.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from .models import PresentationError, StyleReference, _identifier
from .style_registry import StyleManifest


PROFILE_SCHEMA = 1
_MAX_PROFILE_BYTES = 16 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def style_manifest_digest(manifest: StyleManifest) -> str:
    """Stable digest of the complete registered style manifest, including asset hashes."""
    encoded = json.dumps(manifest.as_dict(), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _output_basename(value: str | None) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or not value or value != value.strip()
            or value in {".", ".."} or len(value) > 160
            or "/" in value or "\\" in value or ":" in value
            or any(ord(char) < 32 for char in value)):
        raise ValueError("Presentation output name must be a simple filename of at most 160 characters.")
    return value


@dataclass(frozen=True)
class PresentationBuildProfile:
    """A presentation's explicit target, output name, and optional pinned style.

    ``options`` is deliberately reserved: existing PS-05 adapters reject custom
    renderer options, so PS-06 does not silently store options that cannot run.
    New options may be enabled by a future adapter after capability validation.
    """

    renderer_id: str
    output_format: str
    style: StyleReference | None = None
    output_name: str | None = None
    options: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)
    style_manifest_sha256: str | None = None
    schema_version: int = PROFILE_SCHEMA

    def __post_init__(self) -> None:
        _identifier(self.renderer_id, "Renderer ID")
        _identifier(self.output_format, "Output format")
        if type(self.schema_version) is not int or self.schema_version != PROFILE_SCHEMA:
            raise ValueError("Unsupported presentation profile schema.")
        _output_basename(self.output_name)
        if self.style is not None and not isinstance(self.style, StyleReference):
            raise ValueError("Presentation style must be a pinned StyleReference.")
        if (self.style is None) != (self.style_manifest_sha256 is None):
            raise ValueError("Style reference and its manifest fingerprint must be supplied together.")
        if self.style_manifest_sha256 is not None and not _SHA256.fullmatch(self.style_manifest_sha256):
            raise ValueError("Presentation style fingerprint must be a SHA-256 digest.")
        if not isinstance(self.options, Mapping):
            raise ValueError("Presentation build options must be an object.")
        if self.options:
            raise ValueError("Custom presentation build options are not supported by current renderers.")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "renderer_id": self.renderer_id,
            "output_format": self.output_format,
            "style": None if self.style is None else {
                "identifier": self.style.identifier,
                "version": self.style.version,
                "kind": self.style.kind,
            },
            "style_manifest_sha256": self.style_manifest_sha256,
            "output_name": self.output_name,
            "options": {},
        }

    @classmethod
    def from_dict(cls, raw: object) -> "PresentationBuildProfile":
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version", "renderer_id", "output_format", "style",
            "style_manifest_sha256", "output_name", "options",
        }:
            raise ValueError("Presentation profile has invalid or missing fields.")
        style = raw["style"]
        if style is not None:
            if not isinstance(style, dict) or set(style) != {"identifier", "version", "kind"}:
                raise ValueError("Presentation profile style requires a pinned reference.")
            style = StyleReference(**style)
        return cls(
            renderer_id=raw["renderer_id"], output_format=raw["output_format"],
            style=style, output_name=raw["output_name"], options=raw["options"],
            style_manifest_sha256=raw["style_manifest_sha256"], schema_version=raw["schema_version"],
        )


class PresentationProfileStore:
    """Atomic profile files keyed by canonical project root and relative source.

    Files live beneath the local Workbench base directory, not in documents,
    linked repositories, notebooks, or theme packages. Separate processes can
    observe complete writes without keeping a stale in-memory profile cache.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()

    @staticmethod
    def _identity(project_root: Path, source_path: Path) -> tuple[str, str, str]:
        project_root = Path(project_root).resolve()
        source_path = Path(source_path).resolve()
        if not source_path.is_file() or not source_path.is_relative_to(project_root):
            raise PresentationError("Presentation profile source must be a file inside its project.")
        relative = source_path.relative_to(project_root).as_posix()
        if not relative or relative.startswith("../"):
            raise PresentationError("Presentation profile source path is invalid.")
        identity = hashlib.sha256(
            (str(project_root) + "\0" + relative).encode("utf-8")
        ).hexdigest()
        return str(project_root), relative, identity

    def _path(self, digest: str) -> Path:
        return self.root / "profiles" / digest[:2] / f"{digest}.json"

    def _guard(self, destination: Path) -> None:
        """Reject symlinked config path components, including the profile file."""
        if not destination.is_relative_to(self.root):
            raise PresentationError("Presentation profile path escapes its storage root.")
        if self.root.is_symlink():
            raise PresentationError("Presentation profile storage cannot be symlinked.")
        cursor = self.root
        for part in destination.relative_to(self.root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise PresentationError("Presentation profile path cannot contain symlinks.")

    def load(self, project_root: Path, source_path: Path) -> PresentationBuildProfile | None:
        project, relative, digest = self._identity(project_root, source_path)
        target = self._path(digest)
        self._guard(target)
        if not target.exists():
            return None
        if not target.is_file():
            raise PresentationError("Presentation profile is not a regular file.")
        try:
            if target.stat().st_size > _MAX_PROFILE_BYTES:
                raise ValueError("Presentation profile exceeds the size limit.")
            raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or set(raw) != {"project_root", "source", "profile"}:
                raise ValueError("Presentation profile envelope is invalid.")
            if raw["project_root"] != project or raw["source"] != relative:
                raise ValueError("Presentation profile does not match its source file and project.")
            return PresentationBuildProfile.from_dict(raw["profile"])
        except (OSError, ValueError, TypeError) as exc:
            raise PresentationError(f"Invalid saved presentation profile: {exc}") from exc

    def save(self, project_root: Path, source_path: Path, profile: PresentationBuildProfile) -> None:
        if not isinstance(profile, PresentationBuildProfile):
            raise ValueError("Expected a validated PresentationBuildProfile.")
        project, relative, digest = self._identity(project_root, source_path)
        target = self._path(digest)
        self._guard(target)
        payload = json.dumps({"project_root": project, "source": relative, "profile": profile.as_dict()},
                             indent=2, sort_keys=True) + "\n"
        if len(payload.encode("utf-8")) > _MAX_PROFILE_BYTES:
            raise PresentationError("Presentation profile exceeds the size limit.")
        # Private, local metadata; never create a directory through a symlink.
        for path in (self.root, self.root / "profiles", target.parent):
            if path.is_symlink():
                raise PresentationError("Presentation profile storage cannot be symlinked.")
            path.mkdir(mode=0o700, exist_ok=True)
            if not path.is_dir():
                raise PresentationError("Presentation profile storage is not a directory.")
        self._guard(target)
        fd, temporary = tempfile.mkstemp(prefix=".profile-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._guard(target)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def delete(self, project_root: Path, source_path: Path) -> bool:
        _, _, digest = self._identity(project_root, source_path)
        target = self._path(digest)
        self._guard(target)
        if not target.exists():
            return False
        if not target.is_file():
            raise PresentationError("Presentation profile is not a regular file.")
        target.unlink()
        return True
