"""Persistent, renderer-neutral presentation style packages (PS-03).

The registry deliberately does not parse arbitrary Beamer projects or render styles.
Importers (PS-04+) supply an explicit set of relative asset paths; renderer adapters
(PS-05+) consume a pinned, verified StyleReference. Packages are local, immutable,
and never execute scripts during registration or discovery.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Iterable, Mapping

from .models import PresentationError, StyleReference, _identifier


STYLE_MANIFEST_SCHEMA = 1
_MAX_ASSETS = 4096
_MAX_ASSET_BYTES = 128 * 1024 * 1024
_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")


def _validate_version(value: str) -> str:
    if not isinstance(value, str) or not _VERSION.fullmatch(value) or value in {".", ".."}:
        raise ValueError("Style version must be a safe, nonempty version token.")
    return value


def _validate_token(value: str, field: str) -> str:
    _identifier(value, field)
    if value in {".", ".."}:
        raise ValueError(f"{field} must not be a filesystem traversal token.")
    return value


def _asset_path(value: str) -> str:
    """Accept only canonical POSIX-relative filenames, including nested paths."""
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or value.startswith("/") or "//" in value):
        raise ValueError("Style assets require canonical relative POSIX paths.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or str(PurePosixPath(value)) != value:
        raise ValueError("Style assets cannot contain traversal or noncanonical path components.")
    if any(any(ord(ch) < 32 for ch in part) for part in parts):
        raise ValueError("Style asset paths cannot contain control characters.")
    return value


def _no_symlink_components(path: Path, *, root: Path) -> None:
    """Reject symlinks below root and root itself (rather than following them)."""
    if root.is_symlink():
        raise PresentationError("Presentation style storage/source cannot be a symlink.")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PresentationError("Style path escapes its expected directory.") from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PresentationError("Presentation style paths cannot contain symlinks.")


def _sha256(path: Path) -> tuple[int, str]:
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > _MAX_ASSET_BYTES:
                raise PresentationError("A presentation style asset exceeds the per-file size limit.")
            sha.update(chunk)
    return size, sha.hexdigest()


@dataclass(frozen=True)
class StyleAsset:
    """A copied asset with an expected hash, not a pointer to mutable source."""

    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _asset_path(self.path)
        if type(self.size) is not int or self.size < 0 or self.size > _MAX_ASSET_BYTES:
            raise ValueError("Style asset size is invalid.")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise ValueError("Style asset requires a lowercase SHA-256 digest.")

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class StyleManifest:
    """Versioned, renderer-neutral registry metadata (schema version 1)."""

    identifier: str
    version: str
    kind: str
    label: str
    renderer_ids: tuple[str, ...]
    assets: tuple[StyleAsset, ...] = ()
    description: str = ""
    source_name: str = ""
    schema_version: int = STYLE_MANIFEST_SCHEMA
    entrypoint: str = ""

    def __post_init__(self) -> None:
        _validate_token(self.identifier, "Style identifier")
        _validate_token(self.kind, "Style kind")
        _validate_version(self.version)
        if self.schema_version != STYLE_MANIFEST_SCHEMA or type(self.schema_version) is not int:
            raise ValueError("Unsupported presentation style manifest schema.")
        if not isinstance(self.label, str) or not self.label.strip() or len(self.label) > 160:
            raise ValueError("Style label must be between 1 and 160 characters.")
        if not isinstance(self.description, str) or len(self.description) > 4096:
            raise ValueError("Style description exceeds the limit.")
        if not isinstance(self.source_name, str) or len(self.source_name) > 512:
            raise ValueError("Style source label exceeds the limit.")
        if not isinstance(self.renderer_ids, tuple) or not self.renderer_ids:
            raise ValueError("A style must declare compatible renderers.")
        for renderer in self.renderer_ids:
            _validate_token(renderer, "Renderer ID")
        if self.entrypoint:
            _asset_path(self.entrypoint)
            if self.assets and self.entrypoint not in {asset.path for asset in self.assets}:
                raise ValueError("Style entrypoint must be a declared asset.")
        if len(set(self.renderer_ids)) != len(self.renderer_ids):
            raise ValueError("A style cannot repeat renderer IDs.")
        if not isinstance(self.assets, tuple) or len(self.assets) > _MAX_ASSETS:
            raise ValueError("Too many style assets.")
        if not all(isinstance(asset, StyleAsset) for asset in self.assets):
            raise ValueError("Style assets must carry integrity metadata.")
        if len({asset.path.casefold() for asset in self.assets}) != len(self.assets):
            raise ValueError("Style asset paths must be unique, including by case.")
        if sum(asset.size for asset in self.assets) > _MAX_TOTAL_BYTES:
            raise ValueError("Style assets exceed the total package size limit.")

    @property
    def reference(self) -> StyleReference:
        return StyleReference(self.identifier, self.version, self.kind)

    def as_dict(self) -> dict[str, object]:
        value = {
            "schema_version": self.schema_version,
            "identifier": self.identifier,
            "version": self.version,
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "source_name": self.source_name,
            "renderer_ids": list(self.renderer_ids),
            "assets": [asset.as_dict() for asset in self.assets],
        }
        if self.entrypoint:
            value["entrypoint"] = self.entrypoint
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "StyleManifest":
        if not isinstance(value, dict):
            raise ValueError("Style manifest must be a JSON object.")
        fields = {"schema_version", "identifier", "version", "kind", "label", "description", "source_name", "renderer_ids", "assets"}
        if set(value) not in (fields, fields | {"entrypoint"}):
            raise ValueError("Style manifest fields do not match the supported schema.")
        renderers = value["renderer_ids"]
        assets = value["assets"]
        if not isinstance(renderers, list) or not isinstance(assets, list):
            raise ValueError("Style manifest renderers and assets must be arrays.")
        decoded_assets = []
        for asset in assets:
            if not isinstance(asset, dict) or set(asset) != {"path", "size", "sha256"}:
                raise ValueError("Invalid style asset manifest entry.")
            decoded_assets.append(StyleAsset(**asset))
        return cls(
            identifier=value["identifier"], version=value["version"], kind=value["kind"],
            label=value["label"], description=value["description"], source_name=value["source_name"],
            renderer_ids=tuple(renderers), assets=tuple(decoded_assets), schema_version=value["schema_version"],
            entrypoint=value.get("entrypoint", ""),
        )


@dataclass(frozen=True)
class InstalledStyle:
    """A resolved, integrity-checked local style with a renderer-specific asset root."""

    manifest: StyleManifest
    package_dir: Path

    @property
    def assets_dir(self) -> Path:
        return self.package_dir / "assets"

    def asset(self, relative_path: str) -> Path:
        relative_path = _asset_path(relative_path)
        if relative_path not in {entry.path for entry in self.manifest.assets}:
            raise PresentationError("Requested asset is not declared by the style.")
        path = self.assets_dir / relative_path
        _no_symlink_components(path, root=self.package_dir)
        if not path.is_file():
            raise PresentationError("Registered style asset is missing.")
        return path


class PresentationStyleRegistry:
    """Local, immutable style catalog with explicit asset copying and verification.

    PS-03 accepts only paths explicitly supplied by a trusted caller. It does
    not discover an archive's files or execute its scripts; PS-04 will handle
    theme detection and archive extraction in a separate, validated importer.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()

    def _package_dir(self, reference: StyleReference) -> Path:
        _validate_token(reference.identifier, "Style identifier")
        _validate_token(reference.kind, "Style kind")
        _validate_version(reference.version)
        return self.root / "styles" / reference.kind / reference.identifier / reference.version

    def install(
        self, *, identifier: str, version: str, kind: str, label: str,
        renderer_ids: Iterable[str], source_dir: str | Path | None = None,
        asset_paths: Iterable[str] = (), description: str = "", source_name: str = "",
        entrypoint: str = "",
    ) -> StyleManifest:
        """Copy an explicit asset set into a new, pinned style version.

        No replacement is allowed: revisions must use a new version. Empty-asset
        styles are permitted for built-in/parameter-only theme descriptors.
        """
        reference = StyleReference(identifier, version, kind)
        destination = self._package_dir(reference)
        if self.root.is_symlink():
            raise PresentationError("Presentation style storage cannot be a symlink.")
        if destination.exists() or destination.is_symlink():
            raise PresentationError("This presentation style version is already installed.")
        if isinstance(asset_paths, (str, bytes)):
            raise ValueError("Style assets must be an iterable of relative filenames.")
        paths = tuple(_asset_path(path) for path in asset_paths)
        if len(paths) > _MAX_ASSETS or len({p.casefold() for p in paths}) != len(paths):
            raise ValueError("Style asset list is too large or contains duplicate names.")
        if paths and source_dir is None:
            raise ValueError("Asset source directory is required when assets are declared.")
        source_root = Path(source_dir).expanduser().absolute() if source_dir is not None else None
        if source_root is not None and (not source_root.is_dir() or source_root.is_symlink()):
            raise PresentationError("Style asset source must be a normal directory.")
        # Preflight manifest fields before creating directories or copying assets.
        renderers = tuple(renderer_ids)
        StyleManifest(identifier, version, kind, label, renderers,
                      description=description, source_name=source_name, entrypoint=entrypoint)
        # Never call mkdir(parents=True) through an untrusted registry
        # component: a pre-existing symlink could redirect its side effects.
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise PresentationError("Presentation style storage must be a real directory.")
        cursor = self.root
        for segment in ("styles", kind, identifier):
            cursor = cursor / segment
            if cursor.is_symlink():
                raise PresentationError("Presentation style registry paths cannot contain symlinks.")
            cursor.mkdir(exist_ok=True)
            if not cursor.is_dir():
                raise PresentationError("Presentation style registry path is not a directory.")
        _no_symlink_components(destination.parent, root=self.root)
        staging_path = Path(tempfile.mkdtemp(prefix=".style-install-", dir=self.root))
        try:
            (staging_path / "assets").mkdir()
            asset_records: list[StyleAsset] = []
            total_bytes = 0
            for relative in paths:
                assert source_root is not None
                source = source_root / relative
                _no_symlink_components(source, root=source_root)
                if not source.is_file():
                    raise PresentationError(f"Style asset does not exist: {relative}")
                size = source.stat().st_size
                if size > _MAX_ASSET_BYTES or total_bytes + size > _MAX_TOTAL_BYTES:
                    raise PresentationError("Style asset(s) exceed the package size limit.")
                copied = staging_path / "assets" / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, copied, follow_symlinks=False)
                copied_size, digest = _sha256(copied)
                total_bytes += copied_size
                asset_records.append(StyleAsset(relative, copied_size, digest))
            manifest = StyleManifest(
                identifier, version, kind, label, renderers,
                assets=tuple(sorted(asset_records, key=lambda entry: entry.path)),
                description=description, source_name=source_name, entrypoint=entrypoint,
            )
            (staging_path / "manifest.json").write_text(
                json.dumps(manifest.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8",
            )
            if destination.exists() or destination.is_symlink():
                raise PresentationError("This presentation style version is already installed.")
            try:
                staging_path.rename(destination)
            except OSError as exc:
                raise PresentationError(f"Unable to register the style version: {exc}") from exc
            return manifest
        finally:
            if staging_path.exists():
                shutil.rmtree(staging_path)

    def resolve(
        self, reference: StyleReference, *, renderer_id: str | None = None,
        verify_assets: bool = True,
    ) -> InstalledStyle:
        """Resolve an exact version and optionally verify all local asset digests."""
        destination = self._package_dir(reference)
        _no_symlink_components(destination, root=self.root)
        manifest_file = destination / "manifest.json"
        _no_symlink_components(manifest_file, root=self.root)
        if not manifest_file.is_file():
            raise PresentationError("Requested presentation style version is not installed.")
        try:
            # Manifests are intentionally small, including for large asset sets.
            if manifest_file.stat().st_size > 1024 * 1024:
                raise ValueError("Style manifest is too large.")
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest = StyleManifest.from_dict(data)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PresentationError(f"Invalid presentation style manifest: {exc}") from exc
        if manifest.reference != reference:
            raise PresentationError("Presentation style manifest does not match its registry path.")
        if renderer_id is not None:
            _validate_token(renderer_id, "Renderer ID")
            if renderer_id not in manifest.renderer_ids:
                raise PresentationError("Presentation style is not compatible with this renderer.")
        installed = InstalledStyle(manifest, destination)
        if verify_assets:
            for asset in manifest.assets:
                path = installed.asset(asset.path)
                size, digest = _sha256(path)
                if size != asset.size or digest != asset.sha256:
                    raise PresentationError(f"Presentation style asset failed integrity verification: {asset.path}")
        return installed

    def list_styles(
        self, *, kind: str | None = None, renderer_id: str | None = None,
    ) -> list[StyleManifest]:
        """Discover registered manifests without requiring any rendering tools."""
        if kind is not None:
            _validate_token(kind, "Style kind")
        if renderer_id is not None:
            _validate_token(renderer_id, "Renderer ID")
        base = self.root / "styles"
        if not base.exists():
            return []
        _no_symlink_components(base, root=self.root)
        collected = []
        for kind_dir in sorted(base.iterdir()):
            _no_symlink_components(kind_dir, root=self.root)
            if not kind_dir.is_dir() or (kind is not None and kind_dir.name != kind):
                continue
            for identifier_dir in sorted(kind_dir.iterdir()):
                _no_symlink_components(identifier_dir, root=self.root)
                if not identifier_dir.is_dir():
                    continue
                for version_dir in sorted(identifier_dir.iterdir()):
                    _no_symlink_components(version_dir, root=self.root)
                    if not version_dir.is_dir():
                        continue
                    try:
                        version_ref = StyleReference(identifier_dir.name, version_dir.name, kind_dir.name)
                        manifest = self.resolve(version_ref, verify_assets=False).manifest
                    except (ValueError, PresentationError) as exc:
                        raise PresentationError(f"Corrupt registered style at {version_dir}: {exc}") from exc
                    if renderer_id is None or renderer_id in manifest.renderer_ids:
                        collected.append(manifest)
        return collected

    def uninstall(self, reference: StyleReference) -> None:
        """Remove one exact installed version; preserve other versions and styles."""
        installed = self.resolve(reference, verify_assets=False)
        _no_symlink_components(installed.package_dir, root=self.root)
        # Extra local files are not executed; deletion is confined to this package.
        shutil.rmtree(installed.package_dir)
