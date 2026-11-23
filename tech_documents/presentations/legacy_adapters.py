"""PS-02 adapters: keep notebook exports intact; add direct Markdown export.

This module is intentionally independent of Flask and browser state. It provides
format-specific bindings for the shared presentation service, not theme management.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

from ..notebook_exports import NotebookExportService
from .models import (
    PresentationError,
    PresentationExportRequest,
    PresentationExportResult,
    RendererCapabilities,
)


# renderer -> (label, output format, notebook export ID, Quarto format, extension)
_TARGETS = {
    "beamer": ("Beamer (LaTeX)", "pdf", "beamer", "beamer", ".pdf"),
    "reveal": ("Reveal.js", "html", "reveal", "revealjs", ".html"),
    "powerpoint": ("PowerPoint", "pptx", "pptx", "pptx", ".pptx"),
}


class ExistingExportRenderer:
    """Renderer adapter over the existing notebook exporter and local Quarto.

    Notebook presentation exports continue to use NotebookExportService, preserving
    their paths, stored outputs, nbconvert slideshow flags, and offline Reveal
    assets. Markdown exports use Quarto *directly*, avoiding a lossy notebook
    conversion. Registered styles/options are deliberately unsupported in PS-02.
    """

    def __init__(self, renderer_id: str, notebooks: NotebookExportService) -> None:
        if renderer_id not in _TARGETS:
            raise ValueError(f"Unrecognized presentation renderer: {renderer_id}")
        self.renderer_id = renderer_id
        self.notebooks = notebooks

    def capabilities(self) -> RendererCapabilities:
        label, output, notebook_format, _, _ = _TARGETS[self.renderer_id]
        notebook_formats = {
            item["id"]: item for item in self.notebooks.capabilities()["formats"]
        }
        notebook_cap = notebook_formats[notebook_format]
        quarto = self.notebooks._quarto()
        latex_ready = self.renderer_id != "beamer" or self.notebooks._has_latex()
        markdown_ready = bool(quarto) and latex_ready
        notebook_ready = bool(notebook_cap["available"])
        supported = tuple(kind for kind, ready in (
            ("markdown", markdown_ready), ("notebook", notebook_ready),
        ) if ready)
        reasons = []
        if not quarto:
            reasons.append("Install Quarto for Markdown presentation exports.")
        elif not latex_ready:
            reasons.append("Install a TeX/LaTeX engine for Beamer exports.")
        if not notebook_ready and notebook_cap["reason"] not in reasons:
            reasons.append(str(notebook_cap["reason"]))
        # The PS-01 contract requires nonempty source_kinds even for an
        # unavailable renderer; available=True always reports exact coverage.
        return RendererCapabilities(
            renderer_id=self.renderer_id,
            label=label,
            source_kinds=supported or ("markdown", "notebook"),
            output_formats=(output,),
            style_kinds=(),  # PS-03/PS-05: styles will only be advertised when implemented
            available=bool(supported),
            reason="" if supported else " ".join(reasons),
        )

    def render(self, request: PresentationExportRequest) -> PresentationExportResult:
        _, output, notebook_format, quarto_format, extension = _TARGETS[self.renderer_id]
        if request.output_format != output:
            raise PresentationError("Unsupported output format for presentation renderer.")
        if request.style is not None or request.options:
            raise PresentationError("Presentation styles and build options are not supported until a later sprint.")
        if request.source_kind == "notebook":
            # Reuse the existing implementation, never execute notebook cells.
            export_dir = request.project_root / "builds" / "notebooks"
            self._check_export_directory(request.project_root, export_dir)
            existing = self.notebooks.export(
                request.source_path,
                project_root=request.project_root,
                format_id=notebook_format,
                output_name=request.output_name,
            )
            return PresentationExportResult(self.renderer_id, output, request.project_root / existing["path"])
        if request.source_kind != "markdown":
            raise PresentationError("Source format is not supported by this presentation adapter.")

        quarto = self.notebooks._quarto()
        if not quarto:
            raise PresentationError("Install Quarto for Markdown presentation exports.")
        if self.renderer_id == "beamer" and not self.notebooks._has_latex():
            raise PresentationError("Install a TeX/LaTeX engine for Beamer exports.")

        export_dir = request.project_root / "builds" / "presentations"
        self._check_export_directory(request.project_root, export_dir)
        source_name = request.source_path.name
        source_stem = source_name[:-10] if source_name.lower().endswith(".slides.md") else request.source_path.stem
        stem = self.notebooks._safe_stem(request.output_name or source_stem)
        if stem.lower().endswith(extension):
            stem = stem[:-len(extension)]
        destination = export_dir / f"{stem}{extension}"
        if destination.is_symlink() or not destination.resolve().is_relative_to(request.project_root.resolve()):
            raise PresentationError("Presentation output must remain inside its project and cannot be a symlink.")
        export_dir.mkdir(parents=True, exist_ok=True)
        command = [
            quarto, "render", str(request.source_path), "--to", quarto_format,
            "--output", destination.name, "--output-dir", str(export_dir),
            "--no-execute",
        ]
        try:
            completed = subprocess.run(
                command, cwd=str(request.source_path.parent), text=True,
                capture_output=True, timeout=180, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PresentationError("Presentation rendering timed out after 180 seconds.") from exc
        except OSError as exc:
            raise PresentationError(f"Unable to launch the local Quarto renderer: {exc}") from exc
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "Quarto presentation export failed.").strip()
            raise PresentationError(detail[-4000:])
        if not destination.is_file():
            raise PresentationError("Quarto completed without producing the expected presentation.")
        return PresentationExportResult(self.renderer_id, output, destination)

    @staticmethod
    def _check_export_directory(root: Path, directory: Path) -> None:
        if not directory.resolve().is_relative_to(root.resolve()):
            raise PresentationError("Presentation build directory must remain inside its project.")


def existing_export_renderers(notebooks: NotebookExportService) -> list[ExistingExportRenderer]:
    """Create adapters sharing one existing notebook export service."""
    return [ExistingExportRenderer(identifier, notebooks) for identifier in _TARGETS]
