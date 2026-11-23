"""Offline, integrity-checked portable presentation style bundles (PS-12).

The ZIP is data only: no Makefiles, scripts, external URLs, or renderers execute on
import. Bundles preserve *exact* style manifests/assets and optionally a family.
A bundle can hold a single style or one pinned multi-renderer family.
"""
from __future__ import annotations

import json
import os
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
import tempfile
import zipfile
from typing import Iterable

from .models import PresentationError, StyleReference
from .asset_style_importer import _check_css, _check_pptx
from .profiles import style_manifest_digest
from .style_families import PresentationStyleFamilyRegistry, StyleFamilyManifest
from .style_registry import (
    PresentationStyleRegistry, StyleManifest, _asset_path, _no_symlink_components,
    _MAX_ASSET_BYTES, _MAX_TOTAL_BYTES,
)

BUNDLE_SCHEMA = 1
_MAX_BUNDLE_MEMBERS = 4096
_MAX_BUNDLE_BYTES = _MAX_TOTAL_BYTES  # uncompressed; per-file limits still apply
_MAX_MANIFEST_BYTES = 1024 * 1024


def _prefix(ref: StyleReference) -> str:
    return f"styles/{ref.kind}/{ref.identifier}/{ref.version}"


def _validate_imported_style_assets(manifest: StyleManifest, root: Path) -> None:
    """Preserve PS-11 CSS, SVG and PPTX safety checks across portable imports."""
    paths = {asset.path for asset in manifest.assets}
    if manifest.kind == "reveal":
        for asset in manifest.assets:
            if asset.path.lower().endswith(".css"):
                _check_css((root / asset.path).read_bytes(), asset.path, paths)
            if asset.path.lower().endswith(".svg"):
                data = (root / asset.path).read_bytes()
                if len(data) > 2 * 1024 * 1024:
                    raise PresentationError("Portable SVG exceeds the inspection limit.")
                try:
                    tree = ET.fromstring(data)
                except ET.ParseError as exc:
                    raise PresentationError("Malformed portable SVG style asset.") from exc
                for node in tree.iter():
                    if node.tag.lower().endswith("}script") or node.tag.lower() == "script":
                        raise PresentationError("Executable SVG scripts are not supported in style packages.")
                    for key, url in node.attrib.items():
                        if key.lower().endswith("href") and (url.startswith("//") or re.match(r"[a-z][a-z0-9+.-]*:", url, re.I)):
                            raise PresentationError("Portable SVG cannot reference external resources.")
    if manifest.kind == "powerpoint":
        for asset in manifest.assets:
            if asset.path.lower().endswith(".pptx"):
                _check_pptx((root / asset.path).read_bytes())


def _read_json(package: zipfile.ZipFile, member: str, limit: int) -> dict:
    info = package.getinfo(member)
    if info.file_size > limit:
        raise PresentationError(f"Portable presentation bundle metadata exceeds size limit: {member}")
    try:
        raw = json.loads(package.read(info).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PresentationError(f"Invalid bundle metadata: {member}") from exc
    if not isinstance(raw, dict):
        raise PresentationError(f"Portable bundle metadata must be an object: {member}")
    return raw


def _write_zip_entry(package: zipfile.ZipFile, name: str, data: bytes | Path) -> None:
    # Fixed metadata ensures stable portable outputs across machines.
    entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    entry.compress_type = zipfile.ZIP_DEFLATED
    if isinstance(data, Path):
        with data.open("rb") as source, package.open(entry, "w") as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
    else:
        package.writestr(entry, data)


def export_style_bundle(
    styles: PresentationStyleRegistry, references: Iterable[StyleReference],
    destination: str | Path, *, family: StyleFamilyManifest | None = None,
) -> Path:
    """Export complete pinned styles (and optional family) without changing registry."""
    refs = tuple(sorted(set(references), key=lambda x: (x.kind, x.identifier, x.version)))
    if not refs or len(refs) > 16:
        raise ValueError("Portable style bundle needs 1–16 distinct styles.")
    resolved = [styles.resolve(ref) for ref in refs]  # verifies every local asset
    if family is not None:
        if {v.style for v in family.variants} != set(refs):
            raise PresentationError("Portable family bundle must contain exactly its pinned styles.")
        for variant in family.variants:
            match = next(style for style in resolved if style.manifest.reference == variant.style)
            if style_manifest_digest(match.manifest) != variant.manifest_sha256:
                raise PresentationError("Portable family has a mismatched style manifest.")
    manifest = {
        "schema_version": BUNDLE_SCHEMA,
        "format": "research-workbench-presentation-styles",
        "styles": [style.manifest.as_dict() for style in resolved],
        "family": None if family is None else family.as_dict(),
    }
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise PresentationError("Portable style manifest exceeds the size limit.")
    total = len(encoded) + sum(asset.size for installed in resolved for asset in installed.manifest.assets)
    if total > _MAX_BUNDLE_BYTES:
        raise PresentationError("Portable style bundle exceeds the uncompressed size limit.")
    output = Path(destination).expanduser().absolute()
    if output.suffix.lower() != ".zip" or output.exists() or output.is_symlink():
        raise PresentationError("Choose a new .zip destination for the portable style bundle.")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise PresentationError("Portable style bundle destination must have a real parent directory.")
    fd, temporary = tempfile.mkstemp(prefix=".presentation-bundle-", suffix=".zip", dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=False) as package:
            _write_zip_entry(package, "bundle.json", encoded)
            for installed in resolved:
                prefix = _prefix(installed.manifest.reference)
                record = json.dumps(installed.manifest.as_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
                _write_zip_entry(package, prefix + "/manifest.json", record)
                for asset in installed.manifest.assets:
                    _write_zip_entry(package, prefix + "/assets/" + asset.path, installed.asset(asset.path))
        if output.exists() or output.is_symlink():
            raise PresentationError("Portable bundle destination already exists.")
        os.rename(temporary, output)
        return output
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def import_style_bundle(
    styles: PresentationStyleRegistry, families: PresentationStyleFamilyRegistry,
    source: str | Path,
) -> dict[str, object]:
    """Verify an entire ZIP before publishing; roll back newly added styles on error.

    Existing identical versions may be reused, but never overwritten. An
    existing family version rejects import, avoiding silent family replacement.
    """
    source = Path(source).expanduser().absolute()
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != ".zip":
        raise PresentationError("Portable style import requires a regular local ZIP file.")
    staged: list[StyleReference] = []
    succeeded = False
    try:
        with zipfile.ZipFile(source) as package:
            infos = package.infolist()
            if len(infos) > _MAX_BUNDLE_MEMBERS:
                raise PresentationError("Too many files in portable style bundle.")
            names = [info.filename for info in infos]
            if len(set(names)) != len(names) or "bundle.json" not in names:
                raise PresentationError("Portable style bundle has duplicate or missing metadata.")
            if any(info.is_dir() or info.flag_bits & 1 or info.file_size > _MAX_ASSET_BYTES or
                   info.compress_size > _MAX_BUNDLE_BYTES or
                   (info.file_size > 2 * 1024 * 1024 and info.file_size > max(info.compress_size, 1) * 1000)
                   for info in infos):
                raise PresentationError("Unsafe, encrypted or oversized portable bundle member.")
            if sum(info.file_size for info in infos) > _MAX_BUNDLE_BYTES:
                raise PresentationError("Portable bundle exceeds its uncompressed size limit.")
            for info in infos:
                _asset_path(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode and mode != 0o100000:
                    raise PresentationError("Portable style bundles cannot contain symlinks or special members.")
            payload = _read_json(package, "bundle.json", _MAX_MANIFEST_BYTES)
            if set(payload) != {"schema_version", "format", "styles", "family"} or \
               payload["schema_version"] != BUNDLE_SCHEMA or payload["format"] != "research-workbench-presentation-styles" or \
               not isinstance(payload["styles"], list) or not 1 <= len(payload["styles"]) <= 16:
                raise PresentationError("Unsupported portable presentation style bundle schema.")
            manifests = [StyleManifest.from_dict(raw) for raw in payload["styles"]]
            if len({m.reference for m in manifests}) != len(manifests):
                raise PresentationError("Portable bundle includes repeated style versions.")
            family = None if payload["family"] is None else StyleFamilyManifest.from_dict(payload["family"])
            if family is not None:
                if {v.style for v in family.variants} != {m.reference for m in manifests}:
                    raise PresentationError("Portable family is missing one or more pinned style versions.")
                if any(v.manifest_sha256 != style_manifest_digest(next(
                    m for m in manifests if m.reference == v.style)) for v in family.variants):
                    raise PresentationError("Portable family has a mismatched manifest fingerprint.")
            expected = {"bundle.json"}
            for manifest in manifests:
                prefix = _prefix(manifest.reference)
                expected.add(prefix + "/manifest.json")
                record = _read_json(package, prefix + "/manifest.json", _MAX_MANIFEST_BYTES)
                if StyleManifest.from_dict(record) != manifest:
                    raise PresentationError("Portable bundle contains mismatched style manifest copies.")
                expected.update(prefix + "/assets/" + entry.path for entry in manifest.assets)
            if set(names) != expected:
                raise PresentationError("Portable bundle has missing or unexpected members.")
            # Preflight existing versions before any filesystem modifications.
            missing: list[StyleManifest] = []
            for manifest in manifests:
                path = styles._package_dir(manifest.reference)
                _no_symlink_components(path, root=styles.root)
                if path.exists():
                    installed = styles.resolve(manifest.reference)
                    if installed.manifest != manifest:
                        raise PresentationError("An installed style version differs from its portable bundle.")
                else:
                    missing.append(manifest)
            if family is not None:
                target = families._path(family.identifier, family.version)
                _no_symlink_components(target, root=families.root)
                if target.exists():
                    raise PresentationError("This style family version is already installed.")
            # Stage and verify all assets, including styles that might already be installed,
            # BEFORE publishing a single missing style.
            with tempfile.TemporaryDirectory(prefix="workbench-style-bundle-") as temporary:
                stage = Path(temporary)
                for manifest in manifests:
                    prefix = _prefix(manifest.reference)
                    for asset in manifest.assets:
                        relative = prefix + "/assets/" + asset.path
                        target = stage / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with package.open(relative) as stream, target.open("wb") as dest:
                            size = 0
                            hasher = hashlib.sha256()
                            while chunk := stream.read(1024 * 1024):
                                size += len(chunk)
                                if size > _MAX_ASSET_BYTES:
                                    raise PresentationError("Portable bundle asset exceeds size limit.")
                                hasher.update(chunk)
                                dest.write(chunk)
                        if (size, hasher.hexdigest()) != (asset.size, asset.sha256):
                            raise PresentationError("Portable style asset hash or size does not match manifest.")
                for manifest in manifests:
                    asset_root = stage / _prefix(manifest.reference) / "assets"
                    _validate_imported_style_assets(manifest, asset_root)
                for manifest in missing:
                    root = stage / _prefix(manifest.reference) / "assets"
                    root.mkdir(parents=True, exist_ok=True)
                    actual = styles.install(
                        identifier=manifest.identifier, version=manifest.version,
                        kind=manifest.kind, label=manifest.label, renderer_ids=manifest.renderer_ids,
                        source_dir=root, asset_paths=(a.path for a in manifest.assets),
                        description=manifest.description, source_name=manifest.source_name,
                        entrypoint=manifest.entrypoint,
                    )
                    staged.append(manifest.reference)
                    if actual != manifest:
                        raise PresentationError("Imported style metadata differs from its portable manifest.")
                if family is not None:
                    families.install(family)
            result = {"styles": [m.as_dict() for m in manifests],
                      "family": None if family is None else family.as_dict(),
                      "installed_versions": len(staged)}
            succeeded = True
            return result
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError, ValueError, TypeError) as exc:
        if isinstance(exc, PresentationError):
            raise
        raise PresentationError(f"Invalid portable presentation style bundle: {exc}") from exc
    finally:
        if not succeeded:
            for ref in reversed(staged):
                try:
                    styles.uninstall(ref)
                except (PresentationError, OSError):
                    pass  # Preserve the original import failure.
