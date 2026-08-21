from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from .errors import InvalidPathError, UnsupportedFileTypeError

TEXT_EDITABLE_EXTENSIONS = {".md", ".markdown", ".tex", ".bib", ".txt", ".diagram"}
NOTEBOOK_EXTENSIONS = {".ipynb"}
ALLOWED_EXTENSIONS = TEXT_EDITABLE_EXTENSIONS | NOTEBOOK_EXTENSIONS
DIAGRAM_ASSET_EXTENSIONS = {".svg", ".png", ".pdf"}


def safe_name(value: str, fallback: str = "untitled") -> str:
    """Conservative project/build identifier sanitization."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._")
    return cleaned or fallback


def normalize_relative_path(value: str, *, allow_empty: bool = False) -> str:
    """Normalize a project-relative path while preserving normal filename characters."""
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        if allow_empty:
            return ""
        raise InvalidPathError("A path is required.")

    pure = PurePosixPath(raw)
    if pure.is_absolute():
        raise InvalidPathError("Absolute paths are not allowed.")

    parts: list[str] = []
    for part in pure.parts:
        if part in {"", "."}:
            continue
        if part == ".." or "\x00" in part:
            raise InvalidPathError("Invalid path.")
        parts.append(part)

    if not parts:
        if allow_empty:
            return ""
        raise InvalidPathError("A path is required.")

    return "/".join(parts)


def safe_project_path(documents_dir: Path, project: str) -> Path:
    project_name = safe_name(project, "default")
    path = (documents_dir / project_name).resolve()
    root = documents_dir.resolve()
    if path != root and root not in path.parents:
        raise InvalidPathError("Invalid project path.")
    return path


def safe_item_path(
    documents_dir: Path,
    project: str,
    relative_path: str,
    *,
    allow_empty: bool = False,
) -> Path:
    project_path = safe_project_path(documents_dir, project)
    normalized = normalize_relative_path(relative_path, allow_empty=allow_empty)
    path = (project_path / normalized).resolve() if normalized else project_path.resolve()
    project_root = project_path.resolve()
    if path != project_root and project_root not in path.parents:
        raise InvalidPathError("Path leaves the project directory.")
    return path


def safe_editable_file_path(documents_dir: Path, project: str, relative_path: str) -> Path:
    path = safe_item_path(documents_dir, project, relative_path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError("Unsupported editable file type.")
    return path


def relative_to_project(project_path: Path, item_path: Path) -> str:
    return item_path.relative_to(project_path).as_posix()
