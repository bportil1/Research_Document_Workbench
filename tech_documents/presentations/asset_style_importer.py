"""PS-11: local Reveal.js CSS and PowerPoint reference-template import.

This shares PS-04's bounded directory/ZIP scanner and the immutable PS-03
registry, but does not parse or execute presentation content. CSS is checked
for external resource references; PPTX is validated as an Office package.
"""
from __future__ import annotations

from pathlib import Path
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from .beamer_importer import _FolderSource, _ZipSource, _MAX_MEMBER_BYTES
from .models import PresentationError
from .style_registry import PresentationStyleRegistry, StyleManifest, _asset_path

_CSS_ASSETS = frozenset({
    ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".woff", ".woff2", ".ttf", ".otf",
})
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_CSS_IMPORT = re.compile(r"@import\s+(?:['\"]([^'\"]+)['\"]|url\()", re.I)
_IDENTIFIER = re.compile(r"[^a-z0-9._-]+")


def _check_css(data: bytes, path: str, assets: set[str]) -> None:
    if len(data) > 2 * 1024 * 1024:
        raise PresentationError("CSS theme file exceeds the 2 MiB inspection limit.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PresentationError("CSS theme must be UTF-8 text.") from exc
    # Imports make it difficult to guarantee local-only assets; accept a single
    # self-contained stylesheet plus relative image/font URLs in its bundle.
    if _CSS_IMPORT.search(text):
        raise PresentationError("CSS @import is not supported in offline themes; combine stylesheets first.")
    if re.search(r"(?i)(?:https?|ftp|file)\s*:\s*(?:/|\\)", text) or "//" in re.sub(r"/\*.*?\*/", "", text, flags=re.S):
        raise PresentationError("Offline CSS styles cannot contain external or protocol-relative resources.")
    for _, raw in _CSS_URL.findall(text):
        value = raw.strip()
        if value.startswith("data:") or value.startswith("#"):
            continue
        if value.startswith("./"):
            value = value[2:]
        if not value or any(char in value for char in "?#\\") or value.startswith(("/", ".", "~")):
            raise PresentationError(f"Unsafe or unresolved CSS resource URL in {path}: {value[:80]}")
        try:
            relative = _asset_path(value)
        except ValueError as exc:
            raise PresentationError("CSS theme contains an unsafe resource path.") from exc
        resolved = (Path(path).parent / relative).as_posix()
        if resolved not in assets:
            raise PresentationError(f"CSS theme references an undeclared local asset: {value}")


def _check_pptx(data: bytes) -> None:
    """Reject renamed files and malformed/abusive PPTX reference packages."""
    import io
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            infos = package.infolist()
            if len(infos) > 8192 or sum(item.file_size for item in infos) > 128 * 1024 * 1024:
                raise PresentationError("PowerPoint reference package exceeds safety limits.")
            names = {item.filename for item in infos if not item.is_dir()}
            if any("vbaproject" in name.lower() or name.lower().endswith(".vbs") for name in names):
                raise PresentationError("Macro-enabled PowerPoint assets are not supported as reference templates.")
            if not {"[Content_Types].xml", "ppt/presentation.xml"}.issubset(names):
                raise PresentationError("PowerPoint reference must be a valid .pptx presentation.")
            if not any(name.startswith("ppt/slideMasters/slideMaster") and name.endswith(".xml") for name in names):
                raise PresentationError("PowerPoint reference must contain a slide master.")
            for item in infos:
                if item.flag_bits & 1 or item.file_size > 64 * 1024 * 1024:
                    raise PresentationError("Unsafe PowerPoint reference member.")
                if item.filename.endswith("/"):
                    continue
                if item.filename != "[Content_Types].xml":
                    _asset_path(item.filename)
                mode = (item.external_attr >> 16) & 0o170000
                if mode and mode != 0o100000:
                    raise PresentationError("PowerPoint reference contains an unsupported link or special member.")
            # A reference template must not pull styles/images from remote
            # relationships during a later local rendering operation.
            for name in names:
                if not name.endswith(".rels"):
                    continue
                info = package.getinfo(name)
                if info.file_size > 2 * 1024 * 1024:
                    raise PresentationError("PowerPoint relationship file exceeds the inspection limit.")
                tree = ET.fromstring(package.read(info))
                if any(node.attrib.get("TargetMode", "").lower() == "external" for node in tree.iter()):
                    raise PresentationError("PowerPoint reference has external resource relationships.")
    except (zipfile.BadZipFile, OSError, ValueError, ET.ParseError) as exc:
        raise PresentationError("Unable to read a valid PowerPoint reference document.") from exc


def _open_source(source: str | Path, kind: str):
    path = Path(source).expanduser().absolute()
    if path.is_symlink():
        raise PresentationError("Presentation style import cannot follow symlinks.")
    if path.is_dir():
        return path, _FolderSource(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        return path, _ZipSource(path)
    if path.is_file() and path.suffix.lower() == (".css" if kind == "reveal" else ".pptx"):
        if path.stat().st_size > _MAX_MEMBER_BYTES:
            raise PresentationError("Imported style file exceeds the size limit.")
        return path, None
    raise PresentationError("Choose a style directory, ZIP, or supported standalone CSS/PPTX file.")


def _candidates(source: str | Path, kind: str):
    if kind not in {"reveal", "powerpoint"}:
        raise ValueError("Unsupported auxiliary presentation style kind.")
    path, collection = _open_source(source, kind)
    candidates = {}
    if collection is None:
        candidates[path.name] = (path.name, (path.name,), {path.name: path.read_bytes()})
    else:
        suffix = ".css" if kind == "reveal" else ".pptx"
        for selector in sorted(name for name in collection.names if Path(name).suffix.lower() == suffix):
            parent = Path(selector).parent.as_posix()
            prefix = (parent + "/") if parent != "." else ""
            if kind == "reveal":
                paths = tuple(name for name in collection.names if name.startswith(prefix)
                              and Path(name).suffix.lower() in _CSS_ASSETS)
            else:
                paths = (selector,)
            data = {name[len(prefix):]: collection.read(name, maximum=_MAX_MEMBER_BYTES) for name in paths}
            candidates[selector] = (selector[len(prefix):], tuple(data), data)
    for selector, (entry, asset_paths, contents) in candidates.items():
        if kind == "reveal":
            _check_css(contents[entry], entry, set(asset_paths))
            for name, value in contents.items():
                if Path(name).suffix.lower() != ".svg":
                    continue
                if len(value) > 2 * 1024 * 1024:
                    raise PresentationError("SVG style resource exceeds the inspection limit.")
                try:
                    tree = ET.fromstring(value)
                except ET.ParseError as exc:
                    raise PresentationError("Malformed SVG resource in presentation style.") from exc
                for element in tree.iter():
                    if element.tag.lower().endswith("}script") or element.tag.lower() == "script":
                        raise PresentationError("Executable SVG scripts cannot be imported as style assets.")
                    for key, target in element.attrib.items():
                        if key.lower().endswith("href") and (target.startswith("//") or re.match(r"[a-z][a-z0-9+.-]*:", target, re.I)):
                            raise PresentationError("SVG style resources cannot reference external assets.")
        else:
            _check_pptx(contents[entry])
    return path, candidates


def inspect_asset_style_source(source: str | Path, *, kind: str) -> dict[str, object]:
    path, candidates = _candidates(source, kind)
    return {
        "source_name": path.name,
        "kind": kind,
        "themes": [
            {"selector": selector, "theme_name": Path(entry).stem,
             "asset_paths": list(assets), "project_entrypoints": [],
             "external_packages": [], "warnings": []}
            for selector, (entry, assets, _) in candidates.items()
        ],
        "project_entrypoints": [],
        "warnings": [] if candidates else ["No compatible theme assets were found."],
    }


def import_asset_style(
    registry: PresentationStyleRegistry, source: str | Path, *, kind: str,
    version: str, selector: str | None = None, identifier: str | None = None,
    label: str | None = None, description: str = "",
) -> StyleManifest:
    path, candidates = _candidates(source, kind)
    if selector is None and len(candidates) != 1:
        raise PresentationError("Choose an explicit theme from the inspection results.")
    if selector is None:
        selector = next(iter(candidates))
    if selector not in candidates:
        raise PresentationError("Selected style was not found in this source.")
    entry, asset_paths, data = candidates[selector]
    stem = Path(entry).stem.lower()
    identity = identifier or (kind + "." + _IDENTIFIER.sub("-", stem).strip(".-"))
    title = label or f"{'Reveal.js CSS' if kind == 'reveal' else 'PowerPoint'} — {Path(entry).stem}"
    # Copy only selected style resources. Never extract unrelated project files
    # and never follow paths from a source outside the inspected collection.
    with tempfile.TemporaryDirectory(prefix="presentation-asset-style-") as directory:
        stage = Path(directory)
        for name, content in data.items():
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return registry.install(
            identifier=identity, version=version, kind=kind, label=title,
            renderer_ids=(kind,), source_dir=stage, asset_paths=asset_paths,
            entrypoint=entry, source_name=path.name, description=description,
        )
