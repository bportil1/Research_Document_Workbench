from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .errors import DocumentEngineError


class NotebookExportError(DocumentEngineError):
    status_code = 500


@dataclass(frozen=True)
class ExportFormat:
    id: str
    label: str
    extension: str
    kind: str
    engine: str
    description: str


EXPORT_FORMATS = (
    ExportFormat("html", "HTML document", ".html", "document", "nbconvert", "Portable HTML document with stored notebook outputs."),
    ExportFormat("markdown", "Markdown", ".md", "document", "nbconvert", "Markdown plus extracted output assets."),
    ExportFormat("reveal", "Reveal.js presentation", ".html", "presentation", "nbconvert+reveal", "Offline Reveal.js slides using notebook slideshow metadata."),
    ExportFormat("docx", "Word document", ".docx", "document", "quarto", "Microsoft Word document rendered by Quarto."),
    ExportFormat("pdf", "PDF document", ".pdf", "document", "quarto", "PDF document rendered by Quarto."),
    ExportFormat("pptx", "PowerPoint presentation", ".pptx", "presentation", "quarto", "PowerPoint presentation rendered by Quarto."),
    ExportFormat("beamer", "Beamer PDF presentation", ".pdf", "presentation", "quarto", "LaTeX Beamer presentation rendered by Quarto."),
)


_HIGHLIGHT_COMPAT_SCRIPT = r"""<script data-workbench-highlight-compat>
(function () {
  if (window.hljs) return;
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
  function noop() {}
  window.hljs = {
    highlight: function (code) { return { value: escapeHtml(code) }; },
    highlightAuto: function (code) { return { value: escapeHtml(code) }; },
    highlightElement: noop,
    highlightBlock: noop,
    initHighlighting: noop,
    initHighlightingOnLoad: noop,
    configure: noop,
    registerLanguage: noop,
    registerAliases: noop,
    getLanguage: function () { return null; },
    listLanguages: function () { return []; }
  };
}());
</script>"""


class NotebookExportService:
    """Presentation/export orchestration for existing notebook files.

    The service never executes notebook cells. Exporters consume the outputs
    already stored in the .ipynb file. Network access is not required by this
    service; external tools and browser assets must already be installed.
    """

    def __init__(self, *, static_root: Path | None = None) -> None:
        if static_root is None:
            static_root = Path(__file__).resolve().parent / "web" / "static"
        self.static_root = Path(static_root)

    @staticmethod
    def _has_nbconvert() -> bool:
        return importlib.util.find_spec("nbconvert") is not None

    @staticmethod
    def _quarto() -> str | None:
        return shutil.which("quarto")

    @staticmethod
    def _has_latex() -> bool:
        return any(shutil.which(command) for command in ("xelatex", "lualatex", "pdflatex"))

    def _reveal_root(self) -> Path:
        return self.static_root / "vendor" / "reveal"

    def _has_reveal(self) -> bool:
        root = self._reveal_root()
        return (
            (root / "dist" / "reveal.js").is_file()
            and (root / "dist" / "reveal.css").is_file()
            and (root / "dist" / "theme" / "white.css").is_file()
            and (root / "plugin" / "notes" / "notes.js").is_file()
        )

    def capabilities(self) -> dict[str, Any]:
        has_nbconvert = self._has_nbconvert()
        quarto = self._quarto()
        has_reveal = self._has_reveal()
        has_latex = self._has_latex()
        formats = []
        for spec in EXPORT_FORMATS:
            if spec.engine == "nbconvert":
                available = has_nbconvert
                reason = "" if available else "Install the Workbench notebook export dependency (nbconvert)."
            elif spec.engine == "nbconvert+reveal":
                available = has_nbconvert and has_reveal
                if not has_nbconvert:
                    reason = "Install the Workbench notebook export dependency (nbconvert)."
                elif not has_reveal:
                    reason = "Run scripts/vendor_reveal.py once to install the local Reveal.js assets."
                else:
                    reason = ""
            else:
                available = bool(quarto)
                reason = "" if available else "Install Quarto to enable this format."
                if available and spec.id in {"pdf", "beamer"} and not has_latex:
                    available = False
                    reason = "Install a TeX/LaTeX engine to enable PDF and Beamer export."
            formats.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "extension": spec.extension,
                    "kind": spec.kind,
                    "engine": spec.engine,
                    "description": spec.description,
                    "available": available,
                    "reason": reason,
                }
            )
        return {
            "nbconvert": has_nbconvert,
            "reveal": has_reveal,
            "quarto": bool(quarto),
            "quarto_path": quarto,
            "latex": has_latex,
            "formats": formats,
        }

    @staticmethod
    def _spec(format_id: str) -> ExportFormat:
        for spec in EXPORT_FORMATS:
            if spec.id == format_id:
                return spec
        raise NotebookExportError(f"Unsupported notebook export format: {format_id}")

    @staticmethod
    def _safe_stem(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
        cleaned = cleaned.strip("._")
        return cleaned or "notebook"

    def export(
        self,
        notebook_path: Path,
        *,
        project_root: Path,
        format_id: str,
        output_name: str | None = None,
    ) -> dict[str, Any]:
        notebook_path = notebook_path.resolve()
        project_root = project_root.resolve()
        spec = self._spec(format_id)
        caps = {item["id"]: item for item in self.capabilities()["formats"]}
        capability = caps[format_id]
        if not capability["available"]:
            raise NotebookExportError(capability["reason"])

        export_dir = project_root / "builds" / "notebooks"
        export_dir.mkdir(parents=True, exist_ok=True)
        stem = self._safe_stem(output_name or notebook_path.stem)
        if stem.lower().endswith(spec.extension.lower()):
            stem = stem[: -len(spec.extension)]
        destination = export_dir / f"{stem}{spec.extension}"

        if spec.engine.startswith("nbconvert"):
            self._export_nbconvert(notebook_path, destination, format_id)
        else:
            self._export_quarto(notebook_path, destination, format_id)

        try:
            relative = destination.relative_to(project_root)
        except ValueError as exc:  # pragma: no cover - defensive
            raise NotebookExportError("Notebook export escaped the project directory.") from exc
        return {
            "ok": True,
            "format": format_id,
            "path": relative.as_posix(),
            "size": destination.stat().st_size,
            "engine": spec.engine,
        }

    @staticmethod
    def _with_highlight_compatibility(html: str) -> str:
        if "data-workbench-highlight-compat" in html:
            return html
        head = html.lower().find("<head")
        if head >= 0:
            close = html.find(">", head)
            if close >= 0:
                return html[: close + 1] + _HIGHLIGHT_COMPAT_SCRIPT + html[close + 1 :]
        return _HIGHLIGHT_COMPAT_SCRIPT + html

    def _export_nbconvert(self, notebook_path: Path, destination: Path, format_id: str) -> None:
        try:
            import nbformat
            from nbconvert import HTMLExporter, MarkdownExporter, SlidesExporter
        except ImportError as exc:  # pragma: no cover - guarded by capabilities
            raise NotebookExportError("Notebook export requires nbconvert.") from exc

        try:
            notebook = nbformat.read(notebook_path, as_version=4)
            resources: dict[str, Any] = {
                "metadata": {"path": str(notebook_path.parent)},
                "output_files_dir": f"{destination.stem}_files",
            }
            if format_id == "html":
                exporter = HTMLExporter()
                body, resources = exporter.from_notebook_node(notebook, resources=resources)
                destination.write_text(self._with_highlight_compatibility(body), encoding="utf-8")
            elif format_id == "markdown":
                exporter = MarkdownExporter()
                body, resources = exporter.from_notebook_node(notebook, resources=resources)
                destination.write_text(body, encoding="utf-8")
                self._write_resources(destination, resources)
            elif format_id == "reveal":
                exporter = SlidesExporter()
                reveal_dir = destination.with_name(f"{destination.stem}_reveal")
                exporter.reveal_url_prefix = f"./{reveal_dir.name}"
                body, resources = exporter.from_notebook_node(notebook, resources=resources)
                destination.write_text(self._with_highlight_compatibility(body), encoding="utf-8")
                if reveal_dir.exists():
                    shutil.rmtree(reveal_dir)
                shutil.copytree(self._reveal_root(), reveal_dir)
                self._write_resources(destination, resources)
            else:  # pragma: no cover - guarded by spec
                raise NotebookExportError(f"Unsupported nbconvert format: {format_id}")
        except NotebookExportError:
            raise
        except Exception as exc:
            raise NotebookExportError(f"Notebook export failed: {exc}") from exc

    @staticmethod
    def _write_resources(destination: Path, resources: dict[str, Any]) -> None:
        outputs = resources.get("outputs") or {}
        if not outputs:
            return
        root = destination.parent.resolve()
        for name, payload in outputs.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise NotebookExportError("Notebook exporter produced an unsafe asset path.")
            target = (root / relative).resolve()
            if root not in target.parents:
                raise NotebookExportError("Notebook exporter produced an unsafe asset path.")
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(payload, str):
                target.write_text(payload, encoding="utf-8")
            else:
                target.write_bytes(bytes(payload))

    def _export_quarto(self, notebook_path: Path, destination: Path, format_id: str) -> None:
        quarto = self._quarto()
        if not quarto:  # pragma: no cover - guarded by capabilities
            raise NotebookExportError("Install Quarto to enable this format.")
        target = {
            "docx": "docx",
            "pdf": "pdf",
            "pptx": "pptx",
            "beamer": "beamer",
        }[format_id]
        command = [
            quarto,
            "render",
            str(notebook_path),
            "--to",
            target,
            "--output",
            destination.name,
            "--output-dir",
            str(destination.parent),
        ]
        completed = subprocess.run(
            command,
            cwd=str(notebook_path.parent),
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Quarto export failed.").strip()
            raise NotebookExportError(detail[-4000:])
        if not destination.exists():
            raise NotebookExportError("Quarto completed without producing the expected output file.")


__all__ = ["NotebookExportError", "NotebookExportService", "EXPORT_FORMATS"]
