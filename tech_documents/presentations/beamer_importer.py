"""PS-04: inspect and install reusable Beamer themes from local folders/ZIPs.

No LaTeX is compiled and no imported build scripts are executed. A complete
presentation project is *inspected*, but only the selected theme's resources
are copied into an immutable, renderer-neutral registry package.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat
import tempfile
import zipfile

from .models import PresentationError
from .style_registry import PresentationStyleRegistry, StyleManifest, _asset_path, _no_symlink_components

_MAX_ENTRIES = 20000
_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_TEX_BYTES = 2 * 1024 * 1024
_ALLOWED_ASSET_SUFFIXES = frozenset({
    ".sty", ".cls", ".tex", ".png", ".jpg", ".jpeg", ".pdf",
    ".eps", ".svg", ".ttf", ".otf", ".bib",
})
_THEME_FILE = re.compile(r"beamertheme([A-Za-z0-9_-]+)\.sty\Z")
_BEAMER_CLASS = re.compile(r"\\documentclass\s*(?:\[[^]]*\]\s*)?\{\s*beamer\s*\}")
_THEME_USE = re.compile(r"\\usetheme\s*(?:\[[^]]*\]\s*)?\{\s*([^{}]+?)\s*\}")
_PACKAGE_USE = re.compile(r"\\(?:RequirePackage|usepackage)\s*(?:\[[^]]*\]\s*)?\{([^{}]+)\}")
_INPUT_USE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
_IMAGE_USE = re.compile(r"\\includegraphics\s*(?:\[[^]]*\]\s*)?\{([^{}]+)\}")


def _tex_without_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", text)


@dataclass(frozen=True)
class BeamerThemeCandidate:
    """One importable theme, independent of a project's source slides."""

    selector: str  # location of its beamertheme*.sty relative to source root
    theme_name: str
    asset_paths: tuple[str, ...]  # relative to the theme directory, not the project
    project_entrypoints: tuple[str, ...]
    external_packages: tuple[str, ...]  # names only: local installation is not verified
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "selector": self.selector,
            "theme_name": self.theme_name,
            "asset_paths": list(self.asset_paths),
            "project_entrypoints": list(self.project_entrypoints),
            "external_packages": list(self.external_packages),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class BeamerInspection:
    source_name: str
    themes: tuple[BeamerThemeCandidate, ...]
    project_entrypoints: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "source_name": self.source_name,
            "themes": [candidate.as_dict() for candidate in self.themes],
            "project_entrypoints": list(self.project_entrypoints),
            "warnings": list(self.warnings),
        }


class _FolderSource:
    def __init__(self, root: Path):
        self.root = root
        if root.is_symlink() or not root.is_dir():
            raise PresentationError("Beamer source must be a normal, accessible folder.")
        self.names: dict[str, int] = {}
        count = 0
        total = 0
        seen: set[str] = set()
        def fail(error):
            raise PresentationError(f"Unable to inspect Beamer directory: {error}")
        for folder, dirs, files in os.walk(root, followlinks=False, onerror=fail):
            parent = Path(folder)
            for name in dirs + files:
                path = parent / name
                if path.is_symlink():
                    raise PresentationError("Beamer import does not allow symlinks.")
                count += 1
                if count > _MAX_ENTRIES:
                    raise PresentationError("Beamer directory has too many entries.")
            for name in files:
                full = parent / name
                if not full.is_file():
                    raise PresentationError("Beamer import accepts only regular files.")
                relative = _asset_path(full.relative_to(root).as_posix())
                size = full.stat().st_size
                if size > _MAX_MEMBER_BYTES:
                    raise PresentationError("A Beamer source file is too large.")
                total += size
                if total > _MAX_TOTAL_BYTES:
                    raise PresentationError("Beamer directory is too large to inspect safely.")
                if relative.casefold() in seen:
                    raise PresentationError("Beamer directory contains case-insensitive duplicate paths.")
                seen.add(relative.casefold())
                self.names[relative] = size

    def read(self, relative: str, *, maximum: int) -> bytes:
        if self.names[relative] > maximum:
            raise PresentationError("Beamer file exceeds the inspection size limit.")
        path = self.root / relative
        _no_symlink_components(path, root=self.root)
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
        if len(data) > maximum:
            raise PresentationError("Beamer file exceeds the inspection size limit.")
        return data


class _ZipSource:
    def __init__(self, source: Path):
        if source.is_symlink() or not source.is_file():
            raise PresentationError("Beamer ZIP source must be a regular file.")
        self.source = source
        self.names: dict[str, int] = {}
        self.entries: dict[str, zipfile.ZipInfo] = {}
        total = 0
        seen: set[str] = set()
        try:
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                if len(infos) > _MAX_ENTRIES:
                    raise PresentationError("Beamer ZIP has too many entries.")
                for info in infos:
                    relative = info.filename.rstrip("/") if info.is_dir() else info.filename
                    try:
                        _asset_path(relative)
                    except ValueError as exc:
                        raise PresentationError("Beamer ZIP contains an unsafe entry path.") from exc
                    if relative.casefold() in seen:
                        raise PresentationError("Beamer ZIP contains duplicate entry paths.")
                    seen.add(relative.casefold())
                    mode = stat.S_IFMT(info.external_attr >> 16)
                    if mode and (mode != (stat.S_IFDIR if info.is_dir() else stat.S_IFREG)):
                        raise PresentationError("Beamer ZIP contains a symlink or special file.")
                    if (info.flag_bits & 0x1) or info.file_size > _MAX_MEMBER_BYTES:
                        raise PresentationError("Beamer ZIP contains an encrypted or oversized entry.")
                    if info.is_dir():
                        continue
                    total += info.file_size
                    if total > _MAX_TOTAL_BYTES:
                        raise PresentationError("Beamer ZIP is too large to inspect safely.")
                    if info.file_size > 1024 * 1024 and info.file_size > 200 * max(1, info.compress_size):
                        raise PresentationError("Beamer ZIP has a suspicious compression ratio.")
                    self.names[relative] = info.file_size
                    self.entries[relative] = info
        except (OSError, zipfile.BadZipFile) as exc:
            raise PresentationError(f"Cannot read Beamer ZIP: {exc}") from exc

    def read(self, relative: str, *, maximum: int) -> bytes:
        if self.names[relative] > maximum:
            raise PresentationError("Beamer file exceeds the inspection size limit.")
        try:
            with zipfile.ZipFile(self.source) as archive:
                with archive.open(self.entries[relative]) as handle:
                    data = handle.read(maximum + 1)
        except (OSError, EOFError, RuntimeError, zipfile.BadZipFile) as exc:
            raise PresentationError(f"Unable to read Beamer ZIP entry: {relative}") from exc
        if len(data) > maximum:
            raise PresentationError("Beamer file exceeds the inspection size limit.")
        return data


def _source(path: str | Path) -> _FolderSource | _ZipSource:
    location = Path(path).expanduser().absolute()
    if location.is_symlink():
        raise PresentationError("Beamer source must be a normal file or directory, not a symlink.")
    if location.is_dir():
        return _FolderSource(location)
    if location.suffix.lower() == ".zip":
        return _ZipSource(location)
    raise PresentationError("Beamer import requires a directory or a local .zip archive.")


def _clean_text(source: _FolderSource | _ZipSource, name: str) -> str:
    return _tex_without_comments(source.read(name, maximum=_MAX_TEX_BYTES).decode("utf-8", errors="replace"))


def _inspect(source: _FolderSource | _ZipSource, display_name: str) -> BeamerInspection:
    projects: dict[str, tuple[str, ...]] = {}
    for name in sorted(source.names):
        if Path(name).suffix.lower() != ".tex" or source.names[name] > _MAX_TEX_BYTES:
            continue
        text = _clean_text(source, name)
        if _BEAMER_CLASS.search(text):
            themes = tuple(m.strip() for line in _THEME_USE.findall(text) for m in line.split(","))
            projects[name] = themes

    candidates: list[BeamerThemeCandidate] = []
    for selector in sorted(source.names):
        found = _THEME_FILE.fullmatch(Path(selector).name)
        if not found:
            continue
        folder = Path(selector).parent
        prefix = folder.as_posix() + "/" if folder.as_posix() != "." else ""
        assets = sorted(
            (name[len(prefix):] for name in source.names
             if name.startswith(prefix) and Path(name).suffix.lower() in _ALLOWED_ASSET_SUFFIXES
             and not (Path(name).suffix.lower() == ".tex" and name in projects)),
        )
        # A Beamer project can reference themes stored elsewhere (for example
        # in a TeX installation). Matching \usetheme is a hint, not proof that
        # the project is immediately buildable with only these local assets.
        linked = tuple(name for name, themes in projects.items() if found.group(1) in themes)
        required: set[str] = set()
        warnings: set[str] = set()
        relative_set = set(assets)
        for asset in assets:
            if Path(asset).suffix.lower() not in {".sty", ".cls", ".tex"}:
                continue
            original = prefix + asset
            if source.names[original] > _MAX_TEX_BYTES:
                warnings.add(f"Skipped dependency inspection for large TeX asset: {asset}")
                continue
            text = _clean_text(source, original)
            for match in _PACKAGE_USE.findall(text):
                for package in (part.strip() for part in match.split(",")):
                    if not package or "\\" in package or "#" in package:
                        warnings.add(f"Dynamic package dependency in {asset}; inspect manually")
                        continue
                    if package + ".sty" not in relative_set:
                        required.add(package)
            for target in _INPUT_USE.findall(text):
                if any(x in target for x in "\\#"):
                    warnings.add(f"Dynamic TeX input in {asset}; inspect manually")
                    continue
                in_file = target if Path(target).suffix else target + ".tex"
                base = Path(asset).parent / in_file
                if base.as_posix() not in relative_set:
                    warnings.add(f"Unresolved theme input in {asset}: {target}")
            for target in _IMAGE_USE.findall(text):
                if any(x in target for x in "\\#"):
                    warnings.add(f"Dynamic image path in {asset}; inspect manually")
                    continue
                base = (Path(asset).parent / target).as_posix()
                options = [base] if Path(base).suffix else [base + ext for ext in (".png", ".pdf", ".jpg", ".jpeg", ".eps", ".svg")]
                if not any(name in relative_set for name in options):
                    warnings.add(f"Unresolved theme image in {asset}: {target}")
        candidates.append(BeamerThemeCandidate(
            selector=selector, theme_name=found.group(1), asset_paths=tuple(assets),
            project_entrypoints=linked, external_packages=tuple(sorted(required)),
            warnings=tuple(sorted(warnings)),
        ))
    notes = () if candidates else ("No local beamertheme*.sty files were found; project sources are not a reusable theme.",)
    return BeamerInspection(display_name, tuple(candidates), tuple(sorted(projects)), notes)


def inspect_beamer_source(source: str | Path) -> BeamerInspection:
    """Report local themes, complete Beamer entrypoints, and likely dependencies.

    Introspection is static/best-effort: it does not test TeX package presence,
    compile projects, evaluate macros, or infer missing runtime resources.
    """
    path = Path(source).expanduser().absolute()
    return _inspect(_source(path), path.name)


def import_beamer_style(
    registry: PresentationStyleRegistry, source: str | Path, *,
    version: str, selector: str | None = None, identifier: str | None = None,
    label: str | None = None, description: str = "",
) -> StyleManifest:
    """Install one independently reusable theme (not its presentation content).

    ``selector`` is the exact candidate key returned by inspection. When
    multiple themes exist, the caller must choose one rather than silently
    installing the first. Installation never compiles or runs source content.
    """
    path = Path(source).expanduser().absolute()
    discovered = _source(path)
    inspection = _inspect(discovered, path.name)
    if selector is None and len(inspection.themes) != 1:
        raise PresentationError("Select a Beamer theme from inspection results (zero or multiple candidates).")
    matches = [c for c in inspection.themes if selector is None or c.selector == selector]
    if len(matches) != 1:
        raise PresentationError("Requested Beamer theme selector was not found or is ambiguous.")
    candidate = matches[0]
    identity = identifier or "beamer." + re.sub(r"[^a-z0-9._-]", "-", candidate.theme_name.lower())
    title = label or f"Beamer — {candidate.theme_name}"
    theme_dir = Path(candidate.selector).parent.as_posix()
    prefix = theme_dir + "/" if theme_dir != "." else ""
    entrypoint = candidate.selector[len(prefix):]
    if isinstance(discovered, _FolderSource):
        return registry.install(
            identifier=identity, version=version, kind="beamer", label=title,
            renderer_ids=("beamer",), source_dir=discovered.root / theme_dir,
            asset_paths=candidate.asset_paths, entrypoint=entrypoint,
            source_name=path.name, description=description,
        )
    # Only extract declared theme assets. Everything else in a project ZIP,
    # including Makefiles, slide content, and unrelated PDFs, stays untouched.
    with tempfile.TemporaryDirectory(prefix="beamer-style-import-") as temporary:
        staging = Path(temporary)
        for relative in candidate.asset_paths:
            archived = prefix + relative
            output = staging / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(discovered.read(archived, maximum=_MAX_MEMBER_BYTES))
        return registry.install(
            identifier=identity, version=version, kind="beamer", label=title,
            renderer_ids=("beamer",), source_dir=staging,
            asset_paths=candidate.asset_paths, entrypoint=entrypoint,
            source_name=path.name, description=description,
        )
