from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

from tech_documents.notebook_exports import NotebookExportService


NBCONVERT_AVAILABLE = importlib.util.find_spec("nbconvert") is not None and importlib.util.find_spec("nbformat") is not None


class NotebookPresentationExportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.notebook_path = self.project / "analysis.ipynb"

        import nbformat

        notebook = nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_markdown_cell(
                    "# Results",
                    metadata={"slideshow": {"slide_type": "slide"}},
                ),
                nbformat.v4.new_code_cell(
                    "from pathlib import Path\nPath('should_not_run').write_text('bad')\n42",
                    execution_count=1,
                    outputs=[nbformat.v4.new_output(
                        "execute_result",
                        execution_count=1,
                        data={"text/plain": "42"},
                        metadata={},
                    )],
                    metadata={"slideshow": {"slide_type": "fragment"}},
                ),
                nbformat.v4.new_markdown_cell(
                    "Speaker reminder",
                    metadata={"slideshow": {"slide_type": "notes"}},
                ),
            ]
        )
        nbformat.write(notebook, self.notebook_path)

    def tearDown(self):
        self.tempdir.cleanup()

    def _reveal_static(self) -> Path:
        static = self.root / "static"
        reveal = static / "vendor" / "reveal" / "dist"
        (reveal / "theme").mkdir(parents=True)
        plugin = static / "vendor" / "reveal" / "plugin" / "notes"
        plugin.mkdir(parents=True)
        (reveal / "reveal.js").write_text("// reveal", encoding="utf-8")
        (reveal / "reveal.css").write_text(".reveal{}", encoding="utf-8")
        (reveal / "theme" / "white.css").write_text(".reveal{}", encoding="utf-8")
        (reveal / "theme" / "simple.css").write_text(".reveal{}", encoding="utf-8")
        (plugin / "notes.js").write_text("// notes", encoding="utf-8")
        return static

    @unittest.skipUnless(NBCONVERT_AVAILABLE, "nbconvert is not installed")
    def test_html_export_uses_stored_outputs_without_executing_notebook(self):
        service = NotebookExportService(static_root=self.root / "missing-static")
        result = service.export(
            self.notebook_path,
            project_root=self.project,
            format_id="html",
        )
        output = self.project / result["path"]
        self.assertTrue(output.is_file())
        self.assertIn("Results", output.read_text(encoding="utf-8"))
        self.assertFalse((self.project / "should_not_run").exists())

    @unittest.skipUnless(NBCONVERT_AVAILABLE, "nbconvert is not installed")
    def test_reveal_export_is_offline_and_preserves_slide_metadata(self):
        service = NotebookExportService(static_root=self._reveal_static())
        capabilities = service.capabilities()
        reveal_cap = next(item for item in capabilities["formats"] if item["id"] == "reveal")
        self.assertTrue(reveal_cap["available"])

        result = service.export(
            self.notebook_path,
            project_root=self.project,
            format_id="reveal",
        )
        output = self.project / result["path"]
        html = output.read_text(encoding="utf-8")
        self.assertIn("analysis_reveal", html)
        self.assertIn("fragment", html)
        self.assertTrue((output.parent / "analysis_reveal" / "dist" / "reveal.js").exists())
        self.assertTrue((output.parent / "analysis_reveal" / "plugin" / "notes" / "notes.js").exists())
        self.assertFalse((self.project / "should_not_run").exists())


    @unittest.skipUnless(NBCONVERT_AVAILABLE, "nbconvert is not installed")
    def test_markdown_export_keeps_generated_assets_on_referenced_paths(self):
        import base64
        import nbformat

        png = base64.b64encode(b"fake-png-bytes").decode("ascii")
        notebook = nbformat.read(self.notebook_path, as_version=4)
        notebook.cells.append(nbformat.v4.new_code_cell(
            "display figure",
            execution_count=2,
            outputs=[nbformat.v4.new_output(
                "display_data",
                data={"image/png": png},
                metadata={},
            )],
        ))
        nbformat.write(notebook, self.notebook_path)

        service = NotebookExportService(static_root=self.root / "missing-static")
        result = service.export(
            self.notebook_path,
            project_root=self.project,
            format_id="markdown",
        )
        output = self.project / result["path"]
        markdown = output.read_text(encoding="utf-8")
        self.assertIn("analysis_files/", markdown)
        referenced = next((output.parent / "analysis_files").glob("*.png"))
        self.assertTrue(referenced.is_file())

    def test_capabilities_gate_quarto_formats(self):
        service = NotebookExportService(static_root=self.root / "missing-static")
        capabilities = service.capabilities()
        quarto_formats = [item for item in capabilities["formats"] if item["engine"] == "quarto"]
        if capabilities["quarto"]:
            self.assertTrue(all(item["available"] for item in quarto_formats))
        else:
            self.assertTrue(all(not item["available"] for item in quarto_formats))
            self.assertTrue(all("Quarto" in item["reason"] for item in quarto_formats))


if __name__ == "__main__":
    unittest.main()
