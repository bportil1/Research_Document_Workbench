"""Backward-compatible standalone launcher.

The reusable implementation now lives under :mod:`tech_documents`. Existing
``python app.py`` usage and the former helper names are intentionally retained.
"""

from pathlib import Path

from tech_documents.compilation import (
    compile_with_latexmk,
    compile_with_tectonic,
    prepare_build_workspace as _prepare_build_workspace,
)
from tech_documents.paths import (
    ALLOWED_EXTENSIONS,
    DIAGRAM_ASSET_EXTENSIONS,
    normalize_relative_path,
    relative_to_project,
    safe_name,
)
from tech_documents.web.app import app, engine, run

BASE_DIR = engine.base_dir
DOCUMENTS_DIR = engine.documents_dir
BUILDS_DIR = engine.builds_dir


def ensure_directories() -> None:
    engine.ensure_directories()


def safe_project_path(project: str) -> Path:
    return engine.project_path(project)


def safe_item_path(project: str, relative_path: str, *, allow_empty: bool = False) -> Path:
    return engine.item_path(project, relative_path, allow_empty=allow_empty)


def safe_editable_file_path(project: str, relative_path: str) -> Path:
    return engine.editable_file_path(project, relative_path)


def build_project_tree(project_path: Path):
    return engine.build_project_tree(project_path)


def list_projects():
    return engine.list_projects()


def prepare_build_workspace(project_path: Path, build_id: str):
    return _prepare_build_workspace(project_path, BUILDS_DIR, build_id)


if __name__ == "__main__":
    run()
