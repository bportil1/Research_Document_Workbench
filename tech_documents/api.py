from __future__ import annotations

import base64
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
from .paths import (
    ALLOWED_EXTENSIONS,
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
        self.ensure_directories()

    # ------------------------------------------------------------------
    # Workspace / path helpers
    # ------------------------------------------------------------------
    def ensure_directories(self) -> None:
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.builds_dir.mkdir(parents=True, exist_ok=True)

    def project_path(self, project: str) -> Path:
        return safe_project_path(self.documents_dir, project)

    def item_path(self, project: str, relative_path: str, *, allow_empty: bool = False) -> Path:
        return safe_item_path(self.documents_dir, project, relative_path, allow_empty=allow_empty)

    def editable_file_path(self, project: str, relative_path: str) -> Path:
        return safe_editable_file_path(self.documents_dir, project, relative_path)

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
        for project_dir in sorted(
            (p for p in self.documents_dir.iterdir() if p.is_dir() and not p.is_symlink()),
            key=lambda p: p.name.lower(),
        ):
            tree, files = self.build_project_tree(project_dir)
            projects.append({"name": project_dir.name, "tree": tree, "files": files})
        return projects

    def create_project(self, name: str) -> str:
        project_name = safe_name(name, "new_project")
        project_path = self.project_path(project_name)
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

        return project_name

    def delete_project(self, project: str) -> None:
        project_path = self.project_path(project)
        if not project_path.exists():
            raise ItemNotFoundError("Project does not exist.")
        shutil.rmtree(project_path)

    # ------------------------------------------------------------------
    # Editable text files and directories
    # ------------------------------------------------------------------
    def read_file(self, project: str, filename: str) -> dict[str, str]:
        file_path = self.editable_file_path(project, filename)
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
        file_path.write_text(str(content), encoding="utf-8")
        return relative_to_project(self.project_path(project), file_path)

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
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return relative

    def delete_file(self, project: str, filename: str) -> None:
        file_path = self.item_path(project, filename)
        if not file_path.exists() or not file_path.is_file():
            raise ItemNotFoundError("File does not exist.")
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
    # LaTeX compilation
    # ------------------------------------------------------------------
    def compile_latex(self, project: str, filename: str) -> CompilationResult:
        source_file = self.editable_file_path(project, filename)
        if source_file.suffix.lower() != ".tex":
            raise UnsupportedFileTypeError("Only .tex files can be compiled.")
        if not source_file.exists():
            raise ItemNotFoundError("LaTeX source does not exist.")

        build_id = uuid.uuid4().hex
        project_path = self.project_path(project)
        source_dir, output_dir = prepare_build_workspace(project_path, self.builds_dir, build_id)
        relative_source = source_file.relative_to(project_path)
        build_source_file = source_dir / relative_source

        compiler = None
        if shutil.which("latexmk"):
            compiler = compile_with_latexmk
        elif shutil.which("tectonic"):
            compiler = compile_with_tectonic

        if compiler is None:
            return CompilationResult(
                ok=False,
                status_code=503,
                build_id=build_id,
                error="No LaTeX compiler found.",
                log=(
                    "Install latexmk with:\n"
                    "sudo apt install latexmk texlive-latex-extra\n\n"
                    "or install Tectonic."
                ),
            )

        try:
            result = compiler(build_source_file, output_dir)
        except subprocess.TimeoutExpired:
            return CompilationResult(
                ok=False,
                status_code=504,
                build_id=build_id,
                error="Compilation timed out.",
                log="The LaTeX compiler exceeded the 120-second limit.",
            )

        pdf_path = output_dir / f"{build_source_file.stem}.pdf"
        combined_log = "\n".join(part for part in [result.stdout, result.stderr] if part)

        if result.returncode != 0 or not pdf_path.exists():
            return CompilationResult(
                ok=False,
                status_code=422,
                build_id=build_id,
                error="LaTeX compilation failed.",
                log=combined_log[-30000:],
            )

        return CompilationResult(
            ok=True,
            status_code=200,
            build_id=build_id,
            pdf_path=pdf_path,
            log=combined_log[-30000:],
        )

    def health(self) -> dict[str, bool]:
        return available_compilers()


__all__ = [
    "DocumentEngine",
    "DocumentEngineError",
    "DiagramSyntaxError",
    "SavedDiagramAsset",
]
