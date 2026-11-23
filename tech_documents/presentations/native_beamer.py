"""Static detection of native Beamer entrypoints (no TeX evaluation).

A native project stays a regular Workbench project. Its sources, images,
subfiles and locally installed themes are edited in place using the existing
file editor, then copied into the existing isolated LaTeX build workspace.
"""
from __future__ import annotations

from pathlib import Path
import os
import re

from .models import PresentationError

_BEAMER_CLASS = re.compile(r"\\documentclass\s*(?:\[[^\]]*\]\s*)?\{\s*beamer\s*\}")
_MAX_SOURCE_BYTES = 512 * 1024
_SKIP_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "builds", ".pytest_cache", "__pycache__"}


def _without_comments(source: str) -> str:
    """Preserve escaped percent signs while discarding TeX line comments."""
    lines = []
    for line in source.splitlines():
        for index, character in enumerate(line):
            if character != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                line = line[:index]
                break
        lines.append(line)
    return "\n".join(lines)


def is_beamer_source(source: str) -> bool:
    """Recognize a literal Beamer document class; never expand macros."""
    return bool(_BEAMER_CLASS.search(_without_comments(source)))


def is_beamer_entrypoint(source: Path) -> bool:
    """Only complete standalone Beamer source files are valid entrypoints."""
    if source.suffix.lower() != ".tex" or not source.is_file() or source.is_symlink():
        return False
    try:
        if source.stat().st_size > _MAX_SOURCE_BYTES:
            return False
        return is_beamer_source(source.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def discover_beamer_entrypoints(root: Path, *, maximum_files: int = 5000) -> tuple[str, ...]:
    """List selectable mains beneath a local Documents Root; never enter links.

    A strict scan limit avoids blocking the UI on very large linked repositories.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise PresentationError("Beamer project directory is missing.")
    found: list[str] = []
    scanned = 0
    for directory, folders, filenames in os.walk(root, followlinks=False):
        folder = Path(directory)
        folders[:] = sorted(name for name in folders
                            if name not in _SKIP_DIRECTORIES and not (folder / name).is_symlink())
        for filename in sorted(filenames):
            if not filename.lower().endswith(".tex"):
                continue
            candidate = folder / filename
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
                continue
            scanned += 1
            if scanned > maximum_files:
                raise PresentationError("Beamer project has too many TeX files to scan; open a specific main file instead.")
            if is_beamer_entrypoint(candidate):
                found.append(candidate.relative_to(root).as_posix())
    return tuple(found)
