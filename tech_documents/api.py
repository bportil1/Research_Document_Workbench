from __future__ import annotations

import base64
import json
import binascii
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import uuid
from typing import Any, BinaryIO

from .compilation import (
    CompilationResult,
    available_compilers,
    compile_with_latexmk,
    compile_with_tectonic,
    prepare_build_workspace,
)
from .diagrams import (
    DiagramSyntaxError,
    VALID_DIRECTIONS,
    VALID_PRESETS,
    diagram_to_mermaid,
    insert_figure_reference,
    parse_diagram,
    serialize_diagram,
)
from .errors import (
    DocumentEngineError,
    InvalidPathError,
    ItemConflictError,
    ItemNotFoundError,
    UnsupportedFileTypeError,
)
from .notebooks import NotebookRuntime, notebook_dependencies
from .latex_tools import parse_latex_log, preflight_latex
from .notebook_exports import NotebookExportService
from .paths import (
    ALLOWED_EXTENSIONS,
    NOTEBOOK_EXTENSIONS,
    DIAGRAM_ASSET_EXTENSIONS,
    normalize_relative_path,
    relative_to_project,
    safe_editable_file_path,
    safe_item_path,
    safe_name,
    safe_project_path,
)


@dataclass(frozen=True)
class SavedDiagramAsset:
    path: str
    size: int


class DocumentEngine:
    """Reusable local document/project engine.

    The engine intentionally has no Flask or browser dependency. The standalone web
    application and the future unified Project Assistant can both call this surface.
    """

    def __init__(self, base_dir: str | Path | None = None):
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent
        self.base_dir = Path(base_dir).resolve()
        self.documents_dir = self.base_dir / "documents"
        self.builds_dir = self.base_dir / "builds"
        self.project_registry_path = self.base_dir / ".workbench-projects.json"
        self.notebooks = NotebookRuntime()
        self.notebook_exports = NotebookExportService()
        self.ensure_directories()

    # ------------------------------------------------------------------
    # Workspace / path helpers
    # ------------------------------------------------------------------
    def ensure_directories(self) -> None:
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.builds_dir.mkdir(parents=True, exist_ok=True)

    def _load_project_registry(self) -> dict[str, Any]:
        if not self.project_registry_path.exists():
            return {"version": 1, "projects": {}}
        try:
            raw = json.loads(self.project_registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "projects": {}}
        projects = raw.get("projects") if isinstance(raw, dict) else None
        return {"version": 1, "projects": projects if isinstance(projects, dict) else {}}

    def _save_project_registry(self, registry: dict[str, Any]) -> None:
        self.project_registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.project_registry_path.with_suffix(".tmp")
        temp.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(self.project_registry_path)

    def _project_record(self, project: str) -> dict[str, Any]:
        name = safe_name(project, "default")
        registry = self._load_project_registry()
        record = registry["projects"].get(name, {})
        return record if isinstance(record, dict) else {}

    def project_path(self, project: str) -> Path:
        project_name = safe_name(project, "default")
        record = self._project_record(project_name)
        if record.get("linked") and record.get("path"):
            return Path(str(record["path"])).expanduser().resolve()
        return safe_project_path(self.documents_dir, project_name)

    def item_path(self, project: str, relative_path: str, *, allow_empty: bool = False) -> Path:
        project_path = self.project_path(project).resolve()
        normalized = normalize_relative_path(relative_path, allow_empty=allow_empty)
        path = (project_path / normalized).resolve() if normalized else project_path
        if path != project_path and project_path not in path.parents:
            raise InvalidPathError("Path leaves the project directory.")
        return path

    def editable_file_path(self, project: str, relative_path: str) -> Path:
        path = self.item_path(project, relative_path)
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise UnsupportedFileTypeError("Unsupported editable file type.")
        return path

    def documents_root_path(self, project: str) -> Path:
        project_path = self.project_path(project).resolve()
        record = self._project_record(project)
        relative = normalize_relative_path(str(record.get("documents_root", "")), allow_empty=True)
        path = (project_path / relative).resolve() if relative else project_path
        if path != project_path and project_path not in path.parents:
            raise InvalidPathError("Documents Root leaves the project directory.")
        return path

    def project_context(self, project: str) -> dict[str, Any]:
        name = safe_name(project, "default")
        project_path = self.project_path(name)
        record = self._project_record(name)
        documents_root = normalize_relative_path(str(record.get("documents_root", "")), allow_empty=True)
        documents_path = self.documents_root_path(name)
        return {
            "project": name,
            "project_root": str(project_path),
            "documents_root": documents_root,
            "documents_path": str(documents_path),
            "build_root": str(documents_path),
            "main_tex": str(record.get("main_tex", "") or ""),
            "linked": bool(record.get("linked", False)),
        }

    def set_project_context(
        self,
        project: str,
        *,
        documents_root: str = "",
        main_tex: str = "",
    ) -> dict[str, Any]:
        name = safe_name(project, "default")
        project_path = self.project_path(name).resolve()
        normalized_root = normalize_relative_path(documents_root, allow_empty=True)
        documents_path = (project_path / normalized_root).resolve() if normalized_root else project_path
        if documents_path != project_path and project_path not in documents_path.parents:
            raise InvalidPathError("Documents Root leaves the project directory.")
        if not documents_path.exists() or not documents_path.is_dir():
            raise ItemNotFoundError("Documents Root does not exist.")

        normalized_main = normalize_relative_path(main_tex, allow_empty=True)
        if normalized_main:
            main_path = (project_path / normalized_main).resolve()
            if main_path.suffix.lower() != ".tex" or not main_path.is_file():
                raise ItemNotFoundError("Configured main LaTeX file does not exist.")
            if main_path != documents_path and documents_path not in main_path.parents:
                raise InvalidPathError("Main LaTeX file must be inside the Documents Root.")

        registry = self._load_project_registry()
        record = registry["projects"].setdefault(name, {})
        if not isinstance(record, dict):
            record = {}
            registry["projects"][name] = record
        record["documents_root"] = normalized_root
        record["main_tex"] = normalized_main
        self._save_project_registry(registry)
        return self.project_context(name)

    def link_project(self, path: str | Path, *, name: str | None = None) -> str:
        target = Path(path).expanduser().resolve()
        if not target.exists() or not target.is_dir():
            raise ItemNotFoundError("The folder to attach does not exist.")
        base_name = safe_name(name or target.name, "linked_project")
        registry = self._load_project_registry()
        candidate = base_name
        suffix = 2
        while (self.documents_dir / candidate).exists() or candidate in registry["projects"]:
            existing = registry["projects"].get(candidate)
            if isinstance(existing, dict) and existing.get("linked") and Path(str(existing.get("path", ""))).expanduser().resolve() == target:
                return candidate
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        registry["projects"][candidate] = {
            "linked": True,
            "path": str(target),
            "documents_root": "",
            "main_tex": "",
        }
        self._save_project_registry(registry)
        return candidate

    def build_file_path(self, build_id: str, filename: str) -> Path:
        safe_build_id = safe_name(build_id)
        safe_filename = safe_name(filename)
        build_dir = (self.builds_dir / safe_build_id).resolve()
        output_dir = (build_dir / "output").resolve()
        file_path = (output_dir / safe_filename).resolve()
        builds_root = self.builds_dir.resolve()
        if build_dir != builds_root and builds_root not in build_dir.parents:
            raise InvalidPathError("Invalid build path.")
        if file_path != output_dir and output_dir not in file_path.parents:
            raise InvalidPathError("Invalid build output path.")
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("Build output does not exist.")
        return file_path

    # ------------------------------------------------------------------
    # Project / file tree
    # ------------------------------------------------------------------
    def build_project_tree(self, project_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        flat_files: list[dict[str, Any]] = []

        def walk(directory: Path) -> list[dict[str, Any]]:
            nodes: list[dict[str, Any]] = []
            try:
                children = sorted(
                    (p for p in directory.iterdir() if not p.is_symlink()),
                    key=lambda p: (not p.is_dir(), p.name.lower()),
                )
            except FileNotFoundError:
                return []

            for child in children:
                if child.is_dir() and child.name in {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}:
                    continue
                rel_path = relative_to_project(project_path, child)
                if child.is_dir():
                    nodes.append(
                        {
                            "type": "directory",
                            "name": child.name,
                            "path": rel_path,
                            "children": walk(child),
                        }
                    )
                    continue

                if not child.is_file():
                    continue

                extension = child.suffix.lower()
                info = {
                    "type": "file",
                    "name": child.name,
                    "path": rel_path,
                    "extension": extension,
                    "size": child.stat().st_size,
                    "editable": extension in ALLOWED_EXTENSIONS,
                }
                nodes.append(info)
                flat_files.append(info.copy())
            return nodes

        return walk(project_path), flat_files

    def list_projects(self) -> list[dict[str, Any]]:
        self.ensure_directories()
        projects: list[dict[str, Any]] = []
        registry = self._load_project_registry()
        names = {
            p.name for p in self.documents_dir.iterdir()
            if p.is_dir() and not p.is_symlink()
        }
        names.update(str(name) for name, record in registry["projects"].items() if isinstance(record, dict) and record.get("linked"))

        for name in sorted(names, key=str.lower):
            try:
                project_dir = self.project_path(name)
                if not project_dir.exists() or not project_dir.is_dir():
                    continue
                tree, files = self.build_project_tree(project_dir)
                context = self.project_context(name)
                projects.append({"name": name, "tree": tree, "files": files, **context})
            except DocumentEngineError:
                continue
        return projects

    def create_project(self, name: str) -> str:
        project_name = safe_name(name, "new_project")
        record = self._project_record(project_name)
        if record.get("linked"):
            raise ItemConflictError("A linked project already uses that name.")
        project_path = safe_project_path(self.documents_dir, project_name)
        project_path.mkdir(parents=True, exist_ok=True)

        starter_tex = project_path / "paper.tex"
        starter_bib = project_path / "references.bib"
        starter_md = project_path / "notes.md"
        starter_diagram = project_path / "architecture.diagram"

        if not starter_tex.exists():
            starter_tex.write_text(
                "\\documentclass{article}\n"
                "\\usepackage[utf8]{inputenc}\n"
                "\\usepackage{amsmath,amssymb}\n"
                "\\usepackage{graphicx}\n"
                "\\usepackage{booktabs}\n"
                "\\usepackage{hyperref}\n"
                "\\title{Research Paper}\n"
                "\\author{}\n"
                "\\date{\\today}\n\n"
                "\\begin{document}\n"
                "\\maketitle\n\n"
                "\\section{Introduction}\n\n"
                "\\section{Method}\n\n"
                "\\section{Results}\n\n"
                "\\section{Conclusion}\n\n"
                "\\bibliographystyle{plain}\n"
                "\\bibliography{references}\n"
                "\\end{document}\n",
                encoding="utf-8",
            )

        if not starter_bib.exists():
            starter_bib.write_text(
                "@article{example2026,\n"
                "  title   = {Example Reference},\n"
                "  author  = {Author, Example},\n"
                "  journal = {Example Journal},\n"
                "  year    = {2026}\n"
                "}\n",
                encoding="utf-8",
            )

        if not starter_md.exists():
            starter_md.write_text(
                "# Research Notes\n\n"
                "Use this file for Markdown notes, architecture diagrams, and development logs.\n",
                encoding="utf-8",
            )

        if not starter_diagram.exists():
            starter_diagram.write_text(
                "@direction TB\n"
                "@preset architecture\n\n"
                "Research Question [interface]\n"
                "  -> Analysis Pipeline [service]\n\n"
                "Analysis Pipeline\n"
                "  -> Results [database]\n",
                encoding="utf-8",
            )

        self.set_project_context(project_name, documents_root="", main_tex="paper.tex")
        return project_name

    def delete_project(self, project: str) -> None:
        name = safe_name(project, "default")
        project_path = self.project_path(name)
        if not project_path.exists():
            raise ItemNotFoundError("Project does not exist.")
        self.notebooks.shutdown_under(project_path)
        registry = self._load_project_registry()
        record = registry["projects"].get(name, {})
        if isinstance(record, dict) and record.get("linked"):
            registry["projects"].pop(name, None)
            self._save_project_registry(registry)
            return
        shutil.rmtree(project_path)
        if name in registry["projects"]:
            registry["projects"].pop(name, None)
            self._save_project_registry(registry)

    # ------------------------------------------------------------------
    # Editable text files and directories
    # ------------------------------------------------------------------
    def read_file(self, project: str, filename: str) -> dict[str, str]:
        file_path = self.editable_file_path(project, filename)
        if file_path.suffix.lower() in NOTEBOOK_EXTENSIONS:
            raise UnsupportedFileTypeError("Use the notebook API for .ipynb files.")
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("File does not exist.")
        project_path = self.project_path(project)
        return {
            "project": safe_name(project),
            "filename": relative_to_project(project_path, file_path),
            "content": file_path.read_text(encoding="utf-8"),
        }

    def save_file(self, project: str, filename: str, content: str) -> str:
        if not isinstance(content, str):
            raise DocumentEngineError("Content must be text.")
        file_path = self.editable_file_path(project, filename)
        if file_path.suffix.lower() in NOTEBOOK_EXTENSIONS:
            raise UnsupportedFileTypeError("Use the notebook API for .ipynb files.")
        if not file_path.parent.exists() or not file_path.parent.is_dir():
            raise ItemNotFoundError("Parent directory does not exist.")
        file_path.write_text(content, encoding="utf-8")
        return relative_to_project(self.project_path(project), file_path)

    def create_file(self, project: str, path: str, content: str = "") -> str:
        file_path = self.editable_file_path(project, path)
        if not file_path.parent.exists() or not file_path.parent.is_dir():
            raise ItemNotFoundError("Parent directory does not exist.")
        if file_path.exists():
            raise ItemConflictError("File already exists.")
        if file_path.suffix.lower() in NOTEBOOK_EXTENSIONS:
            self.notebooks.create(file_path)
        else:
            file_path.write_text(str(content), encoding="utf-8")
        return relative_to_project(self.project_path(project), file_path)

    # ------------------------------------------------------------------
    # Jupyter notebooks
    # ------------------------------------------------------------------
    def _notebook_path(self, project: str, filename: str) -> Path:
        file_path = self.editable_file_path(project, filename)
        if file_path.suffix.lower() not in NOTEBOOK_EXTENSIONS:
            raise UnsupportedFileTypeError("Notebook operations require a .ipynb file.")
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("Notebook does not exist.")
        return file_path

    def read_notebook(self, project: str, filename: str) -> dict[str, Any]:
        file_path = self.editable_file_path(project, filename)
        if file_path.suffix.lower() not in NOTEBOOK_EXTENSIONS:
            raise UnsupportedFileTypeError("Notebook operations require a .ipynb file.")
        notebook = self.notebooks.load(file_path)
        return {
            "project": safe_name(project),
            "filename": relative_to_project(self.project_path(project), file_path),
            "notebook": notebook,
            "kernel": self.notebooks.status(file_path),
        }

    def save_notebook(self, project: str, filename: str, notebook: dict[str, Any]) -> str:
        file_path = self.editable_file_path(project, filename)
        if file_path.suffix.lower() not in NOTEBOOK_EXTENSIONS:
            raise UnsupportedFileTypeError("Notebook operations require a .ipynb file.")
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("Notebook does not exist.")
        self.notebooks.save(file_path, notebook)
        return relative_to_project(self.project_path(project), file_path)

    def notebook_kernel_status(self, project: str, filename: str) -> dict[str, Any]:
        file_path = self.editable_file_path(project, filename)
        if file_path.suffix.lower() not in NOTEBOOK_EXTENSIONS:
            raise UnsupportedFileTypeError("Notebook operations require a .ipynb file.")
        return self.notebooks.status(file_path)

    def execute_notebook_cell(
        self,
        project: str,
        filename: str,
        source: str,
        *,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        file_path = self.editable_file_path(project, filename)
        if file_path.suffix.lower() not in NOTEBOOK_EXTENSIONS:
            raise UnsupportedFileTypeError("Notebook operations require a .ipynb file.")
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("Notebook does not exist.")
        return self.notebooks.execute(
            file_path,
            self.project_path(project),
            source,
            timeout=timeout,
        )

    def interrupt_notebook_kernel(self, project: str, filename: str) -> bool:
        file_path = self.editable_file_path(project, filename)
        return self.notebooks.interrupt(file_path)

    def restart_notebook_kernel(self, project: str, filename: str) -> dict[str, Any]:
        file_path = self.editable_file_path(project, filename)
        return self.notebooks.restart(file_path, self.project_path(project))

    def shutdown_notebook_kernel(self, project: str, filename: str) -> bool:
        file_path = self.editable_file_path(project, filename)
        return self.notebooks.shutdown(file_path)

    def notebook_capabilities(self) -> dict[str, Any]:
        return {
            **notebook_dependencies(),
            "presentation": {
                "reveal": self.notebook_exports.capabilities()["reveal"],
            },
            "exports": self.notebook_exports.capabilities(),
        }

    def notebook_export_capabilities(self, project: str, filename: str) -> dict[str, Any]:
        self._notebook_path(project, filename)
        return self.notebook_exports.capabilities()

    def export_notebook(
        self,
        project: str,
        filename: str,
        *,
        format_id: str,
        output_name: str | None = None,
    ) -> dict[str, Any]:
        notebook_path = self._notebook_path(project, filename)
        return self.notebook_exports.export(
            notebook_path,
            project_root=self.project_path(project),
            format_id=format_id,
            output_name=output_name,
        )

    def create_folder(self, project: str, path: str) -> str:
        folder_path = self.item_path(project, path)
        if folder_path.exists():
            raise ItemConflictError("A file or folder already exists at that path.")
        if not folder_path.parent.exists() or not folder_path.parent.is_dir():
            raise ItemNotFoundError("Parent directory does not exist.")
        folder_path.mkdir()
        return relative_to_project(self.project_path(project), folder_path)

    def move_item(self, project: str, source: str, destination: str) -> dict[str, str]:
        source_path = self.item_path(project, source)
        destination_path = self.item_path(project, destination)
        project_path = self.project_path(project)
        if source_path == project_path:
            raise InvalidPathError("The project root cannot be moved.")
        if not source_path.exists():
            raise ItemNotFoundError("Source does not exist.")
        if destination_path.exists():
            raise ItemConflictError("Destination already exists.")
        if not destination_path.parent.exists() or not destination_path.parent.is_dir():
            raise ItemNotFoundError("Destination directory does not exist.")
        if source_path.is_dir() and (destination_path == source_path or source_path in destination_path.parents):
            raise InvalidPathError("A folder cannot be moved inside itself.")

        source_rel = relative_to_project(project_path, source_path)
        self.notebooks.shutdown_under(source_path)
        source_path.rename(destination_path)
        return {
            "source": source_rel,
            "destination": relative_to_project(project_path, destination_path),
        }

    def delete_item(self, project: str, item_path: str) -> str:
        path = self.item_path(project, item_path)
        project_path = self.project_path(project)
        if path == project_path:
            raise InvalidPathError("The project root cannot be deleted here.")
        if not path.exists():
            raise ItemNotFoundError("Item does not exist.")
        relative = relative_to_project(project_path, path)
        self.notebooks.shutdown_under(path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return relative

    def delete_file(self, project: str, filename: str) -> None:
        file_path = self.item_path(project, filename)
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("File does not exist.")
        self.notebooks.shutdown(file_path)
        file_path.unlink()

    def upload_file(self, project: str, filename: str, stream: BinaryIO, folder: str = "") -> str:
        project_path = self.project_path(project)
        project_path.mkdir(parents=True, exist_ok=True)

        original_name = str(filename).replace("\\", "/").split("/")[-1]
        if original_name in {"", ".", ".."} or "\x00" in original_name:
            raise InvalidPathError("Invalid filename.")

        normalized_folder = normalize_relative_path(folder, allow_empty=True)
        relative_path = f"{normalized_folder}/{original_name}" if normalized_folder else original_name
        destination = self.item_path(project, relative_path)
        if not destination.parent.exists() or not destination.parent.is_dir():
            raise ItemNotFoundError("Upload folder does not exist.")
        if destination.exists():
            raise ItemConflictError("A file with that name already exists.")

        with destination.open("wb") as handle:
            shutil.copyfileobj(stream, handle)
        return relative_to_project(project_path, destination)

    # ------------------------------------------------------------------
    # Assets, archiving, and diagrams
    # ------------------------------------------------------------------
    def asset_path(self, project: str, filename: str) -> Path:
        file_path = self.item_path(project, filename)
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("File does not exist.")
        return file_path

    def archive_project(self, project: str) -> Path:
        project_path = self.project_path(project)
        if not project_path.exists():
            raise ItemNotFoundError("Project does not exist.")
        archive_path = self.builds_dir / f"{project_path.name}.zip"
        if archive_path.exists():
            archive_path.unlink()
        shutil.make_archive(str(archive_path.with_suffix("")), "zip", root_dir=project_path)
        return archive_path

    def parse_diagram(self, content: str, *, direction: str | None = None, preset: str | None = None) -> dict[str, Any]:
        if not isinstance(content, str):
            raise DocumentEngineError("Diagram content must be text.")
        document = parse_diagram(content)

        if direction is not None:
            normalized_direction = str(direction).upper()
            if normalized_direction not in VALID_DIRECTIONS:
                raise DocumentEngineError(f"Unsupported direction: {direction}")
            document.direction = normalized_direction

        if preset is not None:
            normalized_preset = str(preset).lower()
            if normalized_preset not in VALID_PRESETS:
                raise DocumentEngineError(f"Unsupported preset: {preset}")
            document.preset = normalized_preset

        return {
            "graph": document.to_dict(),
            "mermaid": diagram_to_mermaid(document),
            "normalized_source": serialize_diagram(document),
        }

    def save_diagram_asset(
        self,
        project: str,
        path: str,
        *,
        encoding: str,
        content: str,
    ) -> SavedDiagramAsset:
        destination = self.item_path(project, path)
        extension = destination.suffix.lower()
        if extension not in DIAGRAM_ASSET_EXTENSIONS:
            raise UnsupportedFileTypeError("Diagram assets must use .svg, .png, or .pdf.")
        if not isinstance(content, str):
            raise DocumentEngineError("Asset content must be text.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        if encoding == "text":
            if extension != ".svg":
                raise DocumentEngineError("Text diagram exports are only valid for SVG files.")
            destination.write_text(content, encoding="utf-8")
        elif encoding == "base64":
            try:
                raw = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError):
                raise DocumentEngineError("Invalid base64 diagram asset.") from None
            destination.write_bytes(raw)
        else:
            raise DocumentEngineError("Unsupported asset encoding.")

        return SavedDiagramAsset(
            path=relative_to_project(self.project_path(project), destination),
            size=destination.stat().st_size,
        )

    def insert_diagram(
        self,
        project: str,
        *,
        target: str,
        asset: str,
        caption: str = "",
        label: str = "",
        figure_mode: str = "single",
        allow_duplicate: bool = False,
    ) -> dict[str, Any]:
        target_rel = normalize_relative_path(target)
        asset_rel = normalize_relative_path(asset)
        target_path = self.editable_file_path(project, target_rel)
        asset_path = self.item_path(project, asset_rel)

        if target_path.suffix.lower() not in {".md", ".markdown", ".tex"}:
            raise UnsupportedFileTypeError("Diagram references can only be inserted into Markdown or LaTeX files.")
        if not target_path.exists() or not target_path.is_file():
            raise ItemNotFoundError("Target document does not exist.")
        if (
            asset_path.suffix.lower() not in DIAGRAM_ASSET_EXTENSIONS
            or not asset_path.exists()
            or not asset_path.is_file()
        ):
            raise ItemNotFoundError("Diagram asset does not exist.")

        try:
            insertion = insert_figure_reference(
                target_path.read_text(encoding="utf-8"),
                target_file=target_rel,
                asset_file=asset_rel,
                caption=caption,
                label=label,
                figure_mode=figure_mode,
                allow_duplicate=allow_duplicate,
            )
        except ValueError as exc:
            raise DocumentEngineError(str(exc)) from exc

        if not insertion.already_present:
            target_path.write_text(insertion.content, encoding="utf-8")

        return {
            "target": target_rel,
            "asset": asset_rel,
            "relative_asset": insertion.relative_asset,
            "snippet": insertion.snippet,
            "label": insertion.label,
            "warning": insertion.warning,
            "already_present": insertion.already_present,
        }

    # ------------------------------------------------------------------
    # LaTeX project setup / diagnostics
    # ------------------------------------------------------------------
    def create_latex_project(
        self,
        project: str,
        *,
        directory: str = "",
        template: str = "article",
        title: str = "Research Document",
        authors: str = "",
        create_bibliography: bool = True,
        create_images: bool = True,
        set_documents_root: bool = True,
    ) -> dict[str, Any]:
        project_path = self.project_path(project).resolve()
        relative_dir = normalize_relative_path(directory, allow_empty=True)
        target = (project_path / relative_dir).resolve() if relative_dir else project_path
        if target != project_path and project_path not in target.parents:
            raise InvalidPathError("LaTeX project directory leaves the project root.")
        target.mkdir(parents=True, exist_ok=True)

        templates = {
            "article": ("article", "plain"),
            "ieee-conference": ("IEEEtran", "IEEEtran"),
            "ieee-journal": ("IEEEtran", "IEEEtran"),
            "report": ("report", "plain"),
            "blank": ("article", "plain"),
        }
        if template not in templates:
            raise DocumentEngineError("Unknown LaTeX template.")
        document_class, bib_style = templates[template]
        class_options = "[conference]" if template == "ieee-conference" else "[journal]" if template == "ieee-journal" else ""
        main = target / "main.tex"
        bib = target / "bib.bib"
        images = target / "images"
        conflicts = [path.name for path in (main, bib) if path.exists()]
        if conflicts:
            raise ItemConflictError(f"LaTeX project would overwrite existing file(s): {', '.join(conflicts)}")

        escaped_title = str(title or "Research Document").replace("\n", " ").strip() or "Research Document"
        escaped_authors = str(authors or "").replace("\n", " ").strip()
        body = [
            f"\\documentclass{class_options}{{{document_class}}}",
            "",
            "\\usepackage{amsmath}",
            "\\usepackage{amssymb}",
            "\\usepackage{graphicx}",
            "\\usepackage{booktabs}",
            "\\usepackage{url}",
            "",
            f"\\title{{{escaped_title}}}",
            f"\\author{{{escaped_authors}}}",
            "",
            "\\begin{document}",
            "\\maketitle",
            "",
            "\\begin{abstract}",
            "Describe the purpose, method, and main result.",
            "\\end{abstract}",
            "",
            "\\section{Introduction}",
            "",
            "\\section{Method}",
            "",
            "\\section{Results}",
            "",
            "\\section{Conclusion}",
            "",
        ]
        if create_bibliography:
            body.extend([f"\\bibliographystyle{{{bib_style}}}", "\\bibliography{bib}", ""])
        body.extend(["\\end{document}", ""])
        main.write_text("\n".join(body), encoding="utf-8")
        if create_bibliography:
            bib.write_text(
                "@article{example2026,\n"
                "  title={Example Reference},\n"
                "  author={Author, Example},\n"
                "  journal={Example Journal},\n"
                "  year={2026}\n"
                "}\n",
                encoding="utf-8",
            )
        if create_images:
            images.mkdir(exist_ok=True)

        main_rel = relative_to_project(project_path, main)
        if set_documents_root:
            self.set_project_context(project, documents_root=relative_dir, main_tex=main_rel)
        return {
            "directory": relative_dir,
            "main_tex": main_rel,
            "bibliography": relative_to_project(project_path, bib) if create_bibliography else "",
            "images": relative_to_project(project_path, images) if create_images else "",
            "template": template,
        }

    def latex_preflight(self, project: str, filename: str) -> dict[str, object]:
        source_file = self.editable_file_path(project, filename)
        if source_file.suffix.lower() != ".tex" or not source_file.is_file():
            raise UnsupportedFileTypeError("LaTeX preflight requires an existing .tex file.")
        return preflight_latex(
            source_file,
            project_root=self.project_path(project),
            documents_root=self.documents_root_path(project),
        ).to_dict()

    # ------------------------------------------------------------------
    # LaTeX compilation
    # ------------------------------------------------------------------
    def compile_latex(self, project: str, filename: str, *, force: bool = False) -> CompilationResult:
        """Compile a LaTeX file from a managed or attached Workbench project."""
        source_file = self.editable_file_path(project, filename)
        project_path = self.project_path(project).resolve()
        documents_root = self.documents_root_path(project).resolve()
        return self._compile_latex_source(
            project_path=project_path,
            documents_root=documents_root,
            source_file=source_file,
            builds_dir=self.builds_dir,
            force=force,
        )

    def compile_latex_path(
        self,
        project_root: str | Path,
        filename: str,
        *,
        builds_dir: str | Path | None = None,
        force: bool = False,
    ) -> CompilationResult:
        """Compile ``filename`` from an arbitrary local project root.

        This is the stable host-facing compatibility entry point used by PAH and
        other callers that already own their workspace.  The caller does not need
        to register the directory as a Workbench project.  The complete supplied
        root is treated as the Documents Root, copied into the isolated build
        workspace, and processed through the same preflight/diagnostic pipeline as
        standalone Workbench builds.
        """
        project_path = Path(project_root).expanduser().resolve()
        if not project_path.exists() or not project_path.is_dir():
            raise ItemNotFoundError("Project root does not exist.")

        relative = Path(str(filename))
        source_file = relative.expanduser().resolve() if relative.is_absolute() else (project_path / relative).resolve()
        try:
            source_file.relative_to(project_path)
        except ValueError as exc:
            raise InvalidPathError("LaTeX source escapes the project root.") from exc

        target_builds = Path(builds_dir).expanduser().resolve() if builds_dir is not None else self.builds_dir
        return self._compile_latex_source(
            project_path=project_path,
            documents_root=project_path,
            source_file=source_file,
            builds_dir=target_builds,
            force=force,
        )

    def _compile_latex_source(
        self,
        *,
        project_path: Path,
        documents_root: Path,
        source_file: Path,
        builds_dir: Path,
        force: bool,
    ) -> CompilationResult:
        source_file = source_file.resolve()
        project_path = project_path.resolve()
        documents_root = documents_root.resolve()
        builds_dir = builds_dir.resolve()

        if source_file.suffix.lower() != ".tex":
            raise UnsupportedFileTypeError("Only .tex files can be compiled.")
        if not source_file.exists() or not source_file.is_file():
            raise ItemNotFoundError("LaTeX source does not exist.")

        try:
            source_file.relative_to(project_path)
        except ValueError as exc:
            raise InvalidPathError("LaTeX source escapes the project root.") from exc
        try:
            relative_source = source_file.relative_to(documents_root)
        except ValueError as exc:
            raise InvalidPathError("LaTeX source must be inside the configured Documents Root.") from exc

        preflight = preflight_latex(source_file, project_root=project_path, documents_root=documents_root)
        preflight_payload = preflight.to_dict()
        if preflight.blockers and not force:
            return CompilationResult(
                ok=False,
                status_code=409,
                error="LaTeX preflight found blockers.",
                diagnostics=tuple(item.to_dict() for item in preflight.diagnostics),
                preflight=preflight_payload,
            )

        build_id = uuid.uuid4().hex
        builds_dir.mkdir(parents=True, exist_ok=True)
        source_dir, output_dir = prepare_build_workspace(documents_root, builds_dir, build_id)
        build_source_file = source_dir / relative_source

        compiler = None
        if shutil.which("latexmk"):
            compiler = compile_with_latexmk
        elif shutil.which("tectonic"):
            compiler = compile_with_tectonic

        if compiler is None:
            diagnostic = {
                "severity": "error",
                "code": "missing-compiler",
                "message": "No LaTeX compiler was found.",
                "file": "",
                "line": None,
                "suggestion": "Install latexmk/TeX Live or Tectonic.",
                "detail": "",
                "secondary": False,
            }
            return CompilationResult(
                ok=False, status_code=503, build_id=build_id, error="No LaTeX compiler found.",
                log="Install latexmk with:\nsudo apt install latexmk texlive-latex-extra\n\nor install Tectonic.",
                diagnostics=(diagnostic,), preflight=preflight_payload,
            )

        try:
            result = compiler(build_source_file, output_dir)
        except subprocess.TimeoutExpired:
            diagnostic = {
                "severity": "error", "code": "compile-timeout", "message": "LaTeX compilation timed out.",
                "file": relative_to_project(project_path, source_file), "line": None,
                "suggestion": "Check for an interactive prompt, runaway expansion, or unusually expensive document step.",
                "detail": "", "secondary": False,
            }
            return CompilationResult(
                ok=False, status_code=504, build_id=build_id, error="Compilation timed out.",
                log="The LaTeX compiler exceeded the 120-second limit.", diagnostics=(diagnostic,),
                preflight=preflight_payload,
            )

        pdf_path = output_dir / f"{build_source_file.stem}.pdf"
        combined_log = "\n".join(part for part in [result.stdout, result.stderr] if part)
        parsed = tuple(item.to_dict() for item in parse_latex_log(combined_log))

        if result.returncode != 0 or not pdf_path.exists():
            return CompilationResult(
                ok=False, status_code=422, build_id=build_id, error="LaTeX compilation failed.",
                log=combined_log[-30000:], diagnostics=parsed, preflight=preflight_payload,
            )

        return CompilationResult(
            ok=True, status_code=200, build_id=build_id, pdf_path=pdf_path,
            log=combined_log[-30000:], diagnostics=parsed, preflight=preflight_payload,
        )

    def health(self) -> dict[str, Any]:
        return {**available_compilers(), "notebooks": notebook_dependencies()}


__all__ = [
    "DocumentEngine",
    "DocumentEngineError",
    "DiagramSyntaxError",
    "SavedDiagramAsset",
]
