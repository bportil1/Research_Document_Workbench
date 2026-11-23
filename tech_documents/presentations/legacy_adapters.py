"""PS-02 adapters: keep notebook exports intact; add direct Markdown export.

This module is intentionally independent of Flask and browser state. It provides
format-specific bindings for the shared presentation service, not theme management.
"""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
import tempfile
from typing import Callable

from ..compilation import CompilationResult
from .native_beamer import is_beamer_entrypoint

from .beamer_rendering import stage_beamer_style
from .style_registry import PresentationStyleRegistry

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
    conversion. A pinned Beamer style can be applied by Quarto without
    changing the original presentation or the legacy unstyled export path.
    """

    def __init__(
        self, renderer_id: str, notebooks: NotebookExportService, *,
        styles: PresentationStyleRegistry | None = None,
        native_compile: Callable[[Path, Path], CompilationResult] | None = None,
    ) -> None:
        if renderer_id not in _TARGETS:
            raise ValueError(f"Unrecognized presentation renderer: {renderer_id}")
        self.renderer_id = renderer_id
        self.notebooks = notebooks
        self.styles = styles
        self.native_compile = native_compile

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
        native_ready = (self.renderer_id == "beamer" and self.native_compile is not None
                        and bool(shutil.which("latexmk") or shutil.which("tectonic")))
        supported = tuple(kind for kind, ready in (
            ("markdown", markdown_ready), ("notebook", notebook_ready), ("latex", native_ready),
        ) if ready)
        reasons = []
        if not quarto:
            reasons.append("Install Quarto for Markdown presentation exports.")
        elif not latex_ready:
            reasons.append("Install a TeX/LaTeX engine for Beamer exports.")
        if not notebook_ready and notebook_cap["reason"] not in reasons:
            reasons.append(str(notebook_cap["reason"]))
        if self.renderer_id == "beamer" and not native_ready:
            reasons.append("Install latexmk/TeX Live or Tectonic for native Beamer projects.")
        # The PS-01 contract requires nonempty source_kinds even for an
        # unavailable renderer; available=True always reports exact coverage.
        return RendererCapabilities(
            renderer_id=self.renderer_id,
            label=label,
            source_kinds=supported or (("markdown", "notebook", "latex") if self.renderer_id == "beamer" else ("markdown", "notebook")),
            output_formats=(output,),
            style_kinds=(self.renderer_id,) if self.styles is not None else (),
            available=bool(supported),
            reason="" if supported else " ".join(reasons),
        )

    def render(self, request: PresentationExportRequest) -> PresentationExportResult:
        _, output, notebook_format, quarto_format, extension = _TARGETS[self.renderer_id]
        if request.output_format != output:
            raise PresentationError("Unsupported output format for presentation renderer.")
        if request.options:
            raise PresentationError("Custom presentation build options are not yet supported.")
        if request.source_kind == "latex":
            if request.style is not None:
                raise PresentationError("Native Beamer projects use their own theme; an installed style cannot be overlaid.")
            return self._render_native_beamer(request)
        if request.style is not None:
            if self.styles is None:
                raise PresentationError("This presentation renderer cannot apply registered styles.")
            if self.renderer_id == "beamer":
                return self._render_styled_beamer(request)
            return self._render_styled_asset_style(request)
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

    def _render_native_beamer(self, request: PresentationExportRequest) -> PresentationExportResult:
        """Build an unchanged multi-file Beamer project through the LaTeX engine.

        The native compiler uses the project's own preamble, bibliography and
        theme assets. We copy only the finished PDF into the shared export area.
        """
        if self.renderer_id != "beamer" or self.native_compile is None:
            raise PresentationError("Native Beamer requires a connected local LaTeX compiler.")
        if request.source_path.suffix.lower() != ".tex" or not is_beamer_entrypoint(request.source_path):
            raise PresentationError("Native Beamer export requires a main .tex with \\documentclass{beamer}.")
        root = request.project_root.resolve()
        export_dir = root / "builds" / "presentations"
        if (root / "builds").is_symlink() or export_dir.is_symlink():
            raise PresentationError("Native Beamer build directories must not be symlinks.")
        self._check_export_directory(root, export_dir)
        # Include the relative source directory in the default name. A project
        # may have multiple independent Beamer mains named presentation.tex.
        default_name = request.source_path.relative_to(root).with_suffix("").as_posix().replace("/", "__")
        stem = self.notebooks._safe_stem(request.output_name or default_name)
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        destination = export_dir / f"{stem}.pdf"
        if destination.is_symlink() or not destination.resolve().is_relative_to(root):
            raise PresentationError("Native Beamer export cannot write outside the project.")
        result = self.native_compile(root, request.source_path)
        if not result.ok or result.pdf_path is None or not result.pdf_path.is_file():
            detail = result.error or "Native Beamer compilation failed."
            raise PresentationError(f"{detail} {result.log[-2500:]}")
        export_dir.mkdir(parents=True, exist_ok=True)
        # Atomic replacement: an unsuccessful build never appears as success.
        with tempfile.NamedTemporaryFile(prefix=".beamer-export-", suffix=".pdf", dir=export_dir, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                with result.pdf_path.open("rb") as compiled:
                    shutil.copyfileobj(compiled, stream)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return PresentationExportResult(self.renderer_id, "pdf", destination)

    def _render_styled_asset_style(self, request: PresentationExportRequest) -> PresentationExportResult:
        """Render a pinned CSS or PPTX reference style via local Quarto.

        Quarto receives its renderer-specific configuration via a temporary
        metadata YAML file (JSON is a YAML subset). Sources and assets remain
        immutable; builds are staged and atomically promoted on success.
        """
        assert request.style is not None and self.styles is not None
        if self.renderer_id not in {"reveal", "powerpoint"} or request.style.kind != self.renderer_id:
            raise PresentationError("Selected presentation style does not match its renderer.")
        if request.source_kind not in {"markdown", "notebook"}:
            raise PresentationError("CSS and PowerPoint styles require Markdown or notebook source.")
        quarto = self.notebooks._quarto()
        if not quarto:
            raise PresentationError("Install local Quarto for styled presentation exports.")
        installed = self.styles.resolve(request.style, renderer_id=self.renderer_id)
        entry = installed.manifest.entrypoint
        if not entry or Path(entry).suffix.lower() != (".css" if self.renderer_id == "reveal" else ".pptx"):
            raise PresentationError("Installed style requires a CSS or PPTX reference entrypoint.")
        folder = "notebooks" if request.source_kind == "notebook" else "presentations"
        export_dir = request.project_root / "builds" / folder
        self._check_export_directory(request.project_root, export_dir)
        stem = request.source_path.stem
        if request.source_kind == "markdown" and request.source_path.name.lower().endswith(".slides.md"):
            stem = request.source_path.name[:-10]
        stem = self.notebooks._safe_stem(request.output_name or stem)
        extension = ".html" if self.renderer_id == "reveal" else ".pptx"
        if stem.lower().endswith(extension):
            stem = stem[:-len(extension)]
        destination = export_dir / f"{stem}{extension}"
        if destination.is_symlink() or not destination.resolve().is_relative_to(request.project_root.resolve()):
            raise PresentationError("Styled presentation output must remain inside the project.")
        export_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".styled-presentation-", dir=export_dir) as directory:
            staged = Path(directory)
            assets = staged / "theme"
            assets.mkdir()
            for record in installed.manifest.assets:
                source = installed.asset(record.path)
                target = assets / record.path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            style_entry = assets / entry
            # Quarto's revealjs 'css' option includes CSS without assuming it
            # is a Sass theme. PPTX 'reference-doc' uses a real .pptx package.
            if self.renderer_id == "reveal":
                # A staged HTML export must remain functional after the
                # temporary build directory is removed. Instruct Quarto to
                # embed its CSS, Reveal libraries, and other resources.
                renderer_options = {"css": str(style_entry), "embed-resources": True}
            else:
                renderer_options = {"reference-doc": str(style_entry)}
            metadata = staged / "style.yml"
            metadata.write_text(json.dumps({"format": {
                "revealjs" if self.renderer_id == "reveal" else "pptx": renderer_options,
            }}), encoding="utf-8")
            output_dir = staged / "output"
            output_dir.mkdir()
            command = [
                quarto, "render", str(request.source_path), "--to",
                "revealjs" if self.renderer_id == "reveal" else "pptx",
                "--output", destination.name, "--output-dir", str(output_dir),
                "--no-execute", "--metadata-file", str(metadata),
            ]
            try:
                result = subprocess.run(command, cwd=str(request.source_path.parent),
                                        capture_output=True, text=True, timeout=180, check=False)
            except subprocess.TimeoutExpired as exc:
                raise PresentationError("Styled presentation rendering timed out after 180 seconds.") from exc
            except OSError as exc:
                raise PresentationError(f"Unable to launch local Quarto: {exc}") from exc
            if result.returncode:
                detail = (result.stderr or result.stdout or "Styled presentation export failed.").strip()
                raise PresentationError(detail[-4000:])
            produced = output_dir / destination.name
            if produced.is_symlink() or not produced.is_file():
                raise PresentationError("Quarto did not produce the expected styled presentation.")
            produced.replace(destination)
        return PresentationExportResult(self.renderer_id, request.output_format, destination)

    def _render_styled_beamer(self, request: PresentationExportRequest) -> PresentationExportResult:
        """Use the same Quarto engine for styled Markdown and stored notebooks.

        Style-free notebooks still take the original NotebookExportService path.
        Quarto is explicitly instructed never to execute notebook cells here.
        """
        assert request.style is not None and self.styles is not None
        if request.source_kind not in {"markdown", "notebook"}:
            raise PresentationError("Styled Beamer exports require Markdown or notebook source.")
        quarto = self.notebooks._quarto()
        if not quarto:
            raise PresentationError("Install Quarto to render presentations with a Beamer style.")
        if not self.notebooks._has_latex():
            raise PresentationError("Install a TeX/LaTeX engine to render styled Beamer presentations.")
        folder = "notebooks" if request.source_kind == "notebook" else "presentations"
        export_dir = request.project_root / "builds" / folder
        self._check_export_directory(request.project_root, export_dir)
        source_stem = request.source_path.stem
        if request.source_kind == "markdown" and request.source_path.name.lower().endswith(".slides.md"):
            source_stem = request.source_path.name[:-10]
        stem = self.notebooks._safe_stem(request.output_name or source_stem)
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        destination = export_dir / f"{stem}.pdf"
        if destination.is_symlink() or not destination.resolve().is_relative_to(request.project_root.resolve()):
            raise PresentationError("Presentation output must remain inside its project and cannot be a symlink.")
        export_dir.mkdir(parents=True, exist_ok=True)
        # A unique output directory prevents a previous successful export from
        # being mistaken for a new one and keeps partial PDFs out of the result.
        with tempfile.TemporaryDirectory(prefix=".beamer-output-", dir=export_dir) as output_temp:
            staged_pdf = Path(output_temp) / destination.name
            with stage_beamer_style(self.styles, request.style) as staged:
                command = [
                    quarto, "render", str(request.source_path), "--to", "beamer",
                    "--output", destination.name, "--output-dir", str(output_temp),
                    "--no-execute", "-M", f"theme:{staged.theme_name}",
                ]
                try:
                    completed = subprocess.run(
                        command, cwd=str(request.source_path.parent), env=dict(staged.environ),
                        text=True, capture_output=True, timeout=180, check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise PresentationError("Styled Beamer rendering timed out after 180 seconds.") from exc
                except OSError as exc:
                    raise PresentationError(f"Unable to launch the local Quarto renderer: {exc}") from exc
                if completed.returncode:
                    detail = (completed.stderr or completed.stdout or "Styled Beamer export failed.").strip()
                    raise PresentationError(detail[-4000:])
            if not staged_pdf.is_file() or staged_pdf.is_symlink():
                raise PresentationError("Quarto completed without producing the expected styled PDF.")
            staged_pdf.replace(destination)
        return PresentationExportResult(self.renderer_id, "pdf", destination)

    @staticmethod
    def _check_export_directory(root: Path, directory: Path) -> None:
        if not directory.resolve().is_relative_to(root.resolve()):
            raise PresentationError("Presentation build directory must remain inside its project.")


def existing_export_renderers(
    notebooks: NotebookExportService, *, styles: PresentationStyleRegistry | None = None,
    native_compile: Callable[[Path, Path], CompilationResult] | None = None,
) -> list[ExistingExportRenderer]:
    """Create adapters sharing one existing notebook export service and style registry."""
    return [ExistingExportRenderer(identifier, notebooks, styles=styles,
                                   native_compile=native_compile if identifier == "beamer" else None)
            for identifier in _TARGETS]
