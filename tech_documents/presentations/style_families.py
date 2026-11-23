"""Version-pinned, renderer-aware presentation style families (PS-12).

A family binds independently rendered Beamer, Reveal and PowerPoint styles.
Branding tokens describe the intended common identity; they are deliberately
metadata, not a promise that arbitrary theme files can be rewritten safely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from .models import PresentationError, StyleReference
from .profiles import style_manifest_digest
from .style_registry import PresentationStyleRegistry, _asset_path, _no_symlink_components, _validate_token, _validate_version

FAMILY_SCHEMA = 1
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_MAX_FAMILY_BYTES = 32 * 1024
_COLOR_KEYS = frozenset({"primary", "secondary", "accent", "background", "foreground"})
_FONT_KEYS = frozenset({"heading", "body", "monospace"})


def _text(value: str, field_name: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"Invalid family {field_name}.")
    if required and not value.strip():
        raise ValueError(f"Family {field_name} is required.")
    return value


@dataclass(frozen=True)
class BrandingTokens:
    """Declarative, validated brand choices, not renderer-side overrides."""

    colors: Mapping[str, str] = field(default_factory=dict)
    fonts: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.colors, Mapping) or not isinstance(self.fonts, Mapping):
            raise ValueError("Branding colors and fonts must be objects.")
        if set(self.colors) - _COLOR_KEYS or set(self.fonts) - _FONT_KEYS:
            raise ValueError("Unsupported branding token.")
        for color in self.colors.values():
            if not isinstance(color, str) or not _COLOR.fullmatch(color):
                raise ValueError("Branding colors must use #RRGGBB values.")
        for font in self.fonts.values():
            _text(font, "font", 80, required=True)

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {"colors": dict(self.colors), "fonts": dict(self.fonts)}

    @classmethod
    def from_dict(cls, raw: object) -> "BrandingTokens":
        if not isinstance(raw, dict) or set(raw) != {"colors", "fonts"}:
            raise ValueError("Branding requires explicit colors and fonts objects.")
        return cls(colors=raw["colors"], fonts=raw["fonts"])


@dataclass(frozen=True)
class StyleFamilyVariant:
    renderer_id: str
    style: StyleReference
    manifest_sha256: str
    branding: BrandingTokens = field(default_factory=BrandingTokens)
    logo_asset: str = ""

    def __post_init__(self) -> None:
        _validate_token(self.renderer_id, "Renderer ID")
        if not isinstance(self.style, StyleReference):
            raise ValueError("Family variant requires an installed StyleReference.")
        if not isinstance(self.manifest_sha256, str) or not _SHA.fullmatch(self.manifest_sha256):
            raise ValueError("Family variant requires a pinned manifest SHA-256.")
        if not isinstance(self.branding, BrandingTokens):
            raise ValueError("Family variant branding is invalid.")
        if not isinstance(self.logo_asset, str):
            raise ValueError("Family logo asset path must be a string.")
        if self.logo_asset:
            _asset_path(self.logo_asset)
            if Path(self.logo_asset).suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp", ".pdf"}:
                raise ValueError("Family logo must be a declared image/PDF asset.")

    def as_dict(self) -> dict[str, object]:
        return {
            "renderer_id": self.renderer_id,
            "style": {"kind": self.style.kind, "identifier": self.style.identifier, "version": self.style.version},
            "manifest_sha256": self.manifest_sha256,
            "branding": self.branding.as_dict(),
            "logo_asset": self.logo_asset,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "StyleFamilyVariant":
        if not isinstance(raw, dict) or set(raw) != {"renderer_id", "style", "manifest_sha256", "branding", "logo_asset"}:
            raise ValueError("Invalid family variant fields.")
        style = raw["style"]
        if not isinstance(style, dict) or set(style) != {"kind", "identifier", "version"}:
            raise ValueError("Invalid pinned family style reference.")
        return cls(raw["renderer_id"], StyleReference(**style), raw["manifest_sha256"],
                   BrandingTokens.from_dict(raw["branding"]), raw["logo_asset"])


@dataclass(frozen=True)
class StyleFamilyManifest:
    identifier: str
    version: str
    label: str
    variants: tuple[StyleFamilyVariant, ...]
    branding: BrandingTokens = field(default_factory=BrandingTokens)
    description: str = ""
    schema_version: int = FAMILY_SCHEMA

    def __post_init__(self) -> None:
        _validate_token(self.identifier, "Family identifier")
        _validate_version(self.version)
        _text(self.label, "label", 160, required=True)
        _text(self.description, "description", 4096)
        if type(self.schema_version) is not int or self.schema_version != FAMILY_SCHEMA:
            raise ValueError("Unsupported style family schema.")
        if not isinstance(self.branding, BrandingTokens):
            raise ValueError("Invalid family branding.")
        if not isinstance(self.variants, tuple) or not (1 <= len(self.variants) <= 16):
            raise ValueError("A family must have 1–16 renderer variants.")
        if any(not isinstance(v, StyleFamilyVariant) for v in self.variants):
            raise ValueError("Invalid style family variant.")
        if len({v.renderer_id for v in self.variants}) != len(self.variants):
            raise ValueError("A family can include only one variant per renderer.")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "identifier": self.identifier, "version": self.version,
            "label": self.label, "description": self.description,
            "branding": self.branding.as_dict(),
            "variants": [v.as_dict() for v in self.variants],
        }

    @classmethod
    def from_dict(cls, raw: object) -> "StyleFamilyManifest":
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version", "identifier", "version", "label", "description", "branding", "variants",
        } or not isinstance(raw["variants"], list):
            raise ValueError("Invalid style family manifest fields.")
        return cls(identifier=raw["identifier"], version=raw["version"], label=raw["label"],
                   description=raw["description"], schema_version=raw["schema_version"],
                   branding=BrandingTokens.from_dict(raw["branding"]),
                   variants=tuple(StyleFamilyVariant.from_dict(v) for v in raw["variants"]))


class PresentationStyleFamilyRegistry:
    """Local immutable family manifests referencing exact installed style versions."""

    def __init__(self, styles: PresentationStyleRegistry) -> None:
        self.styles = styles
        self.root = styles.root

    def _path(self, identifier: str, version: str) -> Path:
        _validate_token(identifier, "Family identifier")
        _validate_version(version)
        return self.root / "families" / identifier / version / "manifest.json"

    def _verify(self, family: StyleFamilyManifest) -> None:
        for variant in family.variants:
            installed = self.styles.resolve(variant.style, renderer_id=variant.renderer_id)
            if style_manifest_digest(installed.manifest) != variant.manifest_sha256:
                raise PresentationError("Family style version has a mismatched manifest fingerprint.")
            if variant.logo_asset and variant.logo_asset not in {asset.path for asset in installed.manifest.assets}:
                raise PresentationError("Family logo is not a declared asset in its renderer style.")

    def create(
        self, *, identifier: str, version: str, label: str,
        variants: Mapping[str, StyleReference], branding: BrandingTokens | None = None,
        overrides: Mapping[str, BrandingTokens] | None = None,
        logos: Mapping[str, str] | None = None, description: str = "",
    ) -> StyleFamilyManifest:
        if not isinstance(variants, Mapping) or not variants:
            raise ValueError("Choose at least one installed style variant.")
        overrides, logos = overrides or {}, logos or {}
        if set(overrides) - set(variants) or set(logos) - set(variants):
            raise ValueError("Renderer overrides must correspond to selected family variants.")
        bound = []
        for renderer_id, ref in sorted(variants.items()):
            installed = self.styles.resolve(ref, renderer_id=renderer_id)
            bound.append(StyleFamilyVariant(renderer_id, ref, style_manifest_digest(installed.manifest),
                                            overrides.get(renderer_id, BrandingTokens()), logos.get(renderer_id, "")))
        family = StyleFamilyManifest(identifier, version, label, tuple(bound), branding or BrandingTokens(), description)
        return self.install(family)

    def install(self, family: StyleFamilyManifest) -> StyleFamilyManifest:
        if not isinstance(family, StyleFamilyManifest):
            raise ValueError("Expected a validated style family manifest.")
        self._verify(family)
        target = self._path(family.identifier, family.version)
        _no_symlink_components(target, root=self.root)
        if target.exists():
            raise PresentationError("This style family version already exists.")
        # Validate size before any directory creation.
        payload = json.dumps(family.as_dict(), sort_keys=True, indent=2) + "\n"
        if len(payload.encode("utf-8")) > _MAX_FAMILY_BYTES:
            raise PresentationError("Style family manifest exceeds the size limit.")
        cursor = self.root
        if cursor.is_symlink():
            raise PresentationError("Style family registry cannot be a symlink.")
        cursor.mkdir(parents=True, exist_ok=True)
        for segment in ("families", family.identifier, family.version):
            cursor = cursor / segment
            if cursor.is_symlink():
                raise PresentationError("Style family paths cannot be symlinked.")
            cursor.mkdir(exist_ok=True)
        _no_symlink_components(target, root=self.root)
        if target.exists():
            raise PresentationError("This style family version already exists.")
        fd, temporary = tempfile.mkstemp(prefix=".family-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists() or target.is_symlink():
                raise PresentationError("This style family version already exists.")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return family

    def resolve(self, identifier: str, version: str, *, verify_styles: bool = True) -> StyleFamilyManifest:
        path = self._path(identifier, version)
        _no_symlink_components(path, root=self.root)
        if not path.is_file():
            raise PresentationError("Requested presentation style family is not installed.")
        try:
            if path.stat().st_size > _MAX_FAMILY_BYTES:
                raise ValueError("Style family manifest exceeds the size limit.")
            family = StyleFamilyManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise PresentationError(f"Invalid saved style family: {exc}") from exc
        if (family.identifier, family.version) != (identifier, version):
            raise PresentationError("Family manifest does not match its registry path.")
        if verify_styles:
            self._verify(family)
        return family

    def list_families(self, *, renderer_id: str | None = None) -> list[StyleFamilyManifest]:
        if renderer_id is not None:
            _validate_token(renderer_id, "Renderer ID")
        root = self.root / "families"
        if not root.exists():
            return []
        _no_symlink_components(root, root=self.root)
        found = []
        for identifier in sorted(root.iterdir()):
            _no_symlink_components(identifier, root=self.root)
            if not identifier.is_dir():
                continue
            for version in sorted(identifier.iterdir()):
                _no_symlink_components(version, root=self.root)
                if not version.is_dir():
                    continue
                family = self.resolve(identifier.name, version.name)
                if renderer_id is None or renderer_id in {v.renderer_id for v in family.variants}:
                    found.append(family)
        return found

    def uninstall(self, identifier: str, version: str) -> None:
        self.resolve(identifier, version, verify_styles=False)
        target = self._path(identifier, version)
        _no_symlink_components(target, root=self.root)
        target.unlink()
        target.parent.rmdir()
        try:
            target.parent.parent.rmdir()
        except OSError:
            pass  # Other family versions remain installed.
        # Removing a family never removes installed styles or presentations.
