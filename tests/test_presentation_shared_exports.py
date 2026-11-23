"""PS-02: shared presentation export routing, security and legacy compatibility."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tech_documents import DocumentEngine
from tech_documents.errors import UnsupportedFileTypeError
from tech_documents.presentations import PresentationError, PresentationExportRequest


class SharedPresentationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = DocumentEngine(Path(self.temp.name) / "workspace")
        self.project = self.engine.create_project("demo")
        self.root = self.engine.project_path(self.project)
        self.engine.create_file(self.project, "talk.slides.md", "# Introduction\n\n---\n\n# Analysis\n")
        self.source = self.root / "talk.slides.md"

    def fake_quarto(self, args, *, cwd, **kwargs):
        self.assertEqual(args[1], "render")
        self.assertIn("--no-execute", args)
        self.assertEqual(cwd, str(self.source.parent))
        destination = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"local presentation")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def test_markdown_beamer_exports_directly_without_editing_source(self):
        original = self.source.read_bytes()
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="/local/quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=self.fake_quarto) as runner:
            result = self.engine.export_presentation(
                self.project, "talk.slides.md", renderer_id="beamer", output_format="pdf",
            )
            self.assertTrue(next(x for x in self.engine.presentation_renderer_capabilities() if x["id"] == "beamer")["available"])
        self.assertEqual(result["path"], "builds/presentations/talk.pdf")
        self.assertEqual(result["format"], "pdf")
        self.assertEqual(result["renderer"], "beamer")
        self.assertEqual(result["source_kind"], "markdown")
        self.assertTrue((self.root / result["path"]).is_file())
        self.assertEqual(self.source.read_bytes(), original)
        command = runner.call_args.args[0]
        self.assertEqual(command[command.index("--to") + 1], "beamer")

    def test_markdown_reveal_and_powerpoint_share_export_api(self):
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=self.fake_quarto):
            for renderer, fmt, extension, quarto_format in (
                ("reveal", "html", ".html", "revealjs"),
                ("powerpoint", "pptx", ".pptx", "pptx"),
            ):
                with self.subTest(renderer=renderer):
                    result = self.engine.export_presentation(
                        self.project, "talk.slides.md", renderer_id=renderer,
                        output_format=fmt, output_name=f"named{extension}",
                    )
                    self.assertEqual(result["path"], f"builds/presentations/named{extension}")
                    self.assertTrue((self.root / result["path"]).is_file())
            catalog = self.engine.presentation_export_capabilities(self.project, "talk.slides.md")
            self.assertEqual(catalog["source_kind"], "markdown")
            self.assertEqual({x["id"] for x in catalog["renderers"]}, {"beamer", "reveal", "powerpoint"})

    def test_notebook_legacy_presentation_route_uses_shared_service_and_keeps_payload(self):
        self.engine.create_file(self.project, "analysis.ipynb")

        def legacy_export(source, *, project_root, format_id, output_name):
            self.assertEqual(source, self.root / "analysis.ipynb")
            self.assertEqual(format_id, "beamer")
            destination = project_root / "builds" / "notebooks" / "demo.pdf"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"%PDF-1.4")
            return {"ok": True, "format": format_id, "path": "builds/notebooks/demo.pdf", "size": 8, "engine": "quarto"}

        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True), \
             patch.object(self.engine.notebook_exports, "export", side_effect=legacy_export) as exporter:
            result = self.engine.export_notebook(
                self.project, "analysis.ipynb", format_id="beamer", output_name="demo",
            )
        self.assertEqual(result, {
            "ok": True, "format": "beamer", "path": "builds/notebooks/demo.pdf", "size": 8, "engine": "quarto",
        })
        self.assertEqual(exporter.call_count, 1)

    @unittest.skipUnless(
        importlib.util.find_spec("nbconvert") is not None and importlib.util.find_spec("nbformat") is not None,
        "nbconvert is not installed",
    )
    def test_offline_notebook_reveal_export_preserved_through_shared_route(self):
        import nbformat
        source = self.root / "analysis.ipynb"
        notebook = nbformat.v4.new_notebook(cells=[
            nbformat.v4.new_markdown_cell("# Offline talk", metadata={"slideshow": {"slide_type": "slide"}}),
            nbformat.v4.new_code_cell(
                "from pathlib import Path; Path('should_not_run').touch()",
                metadata={"slideshow": {"slide_type": "fragment"}},
            ),
        ])
        nbformat.write(notebook, source)
        static = self.root / "static"
        (static / "vendor" / "reveal" / "dist" / "theme").mkdir(parents=True)
        (static / "vendor" / "reveal" / "plugin" / "notes").mkdir(parents=True)
        for name in ("dist/reveal.js", "dist/reveal.css", "dist/theme/white.css", "plugin/notes/notes.js"):
            target = static / "vendor" / "reveal" / name
            target.write_text("/* offline */", encoding="utf-8")
        self.engine.notebook_exports.static_root = static
        result = self.engine.export_notebook(self.project, "analysis.ipynb", format_id="reveal")
        self.assertEqual(result["format"], "reveal")
        self.assertEqual(result["path"], "builds/notebooks/analysis.html")
        self.assertEqual(result["engine"], "nbconvert+reveal")
        html = (self.root / result["path"]).read_text(encoding="utf-8")
        self.assertIn("Offline talk", html)
        self.assertTrue((self.root / "builds" / "notebooks" / "analysis_reveal" / "dist" / "reveal.js").is_file())
        self.assertFalse((self.root / "should_not_run").exists())

    def test_non_presentation_notebook_export_still_uses_existing_service(self):
        self.engine.create_file(self.project, "analysis.ipynb")
        sentinel = {"ok": True, "format": "html", "path": "builds/notebooks/a.html", "size": 7, "engine": "nbconvert"}
        with patch.object(self.engine.notebook_exports, "export", return_value=sentinel) as exporter:
            result = self.engine.export_notebook(self.project, "analysis.ipynb", format_id="html")
        self.assertEqual(result, sentinel)
        exporter.assert_called_once()

    def test_requires_quarto_for_markdown_and_keeps_style_unsupported(self):
        with patch.object(self.engine.notebook_exports, "_quarto", return_value=None):
            catalog = self.engine.presentation_export_capabilities(self.project, "talk.slides.md")
            self.assertFalse(any(x["available"] for x in catalog["renderers"]))
            with self.assertRaisesRegex(PresentationError, "Install Quarto|not connected"):
                self.engine.export_presentation(self.project, "talk.slides.md", renderer_id="powerpoint", output_format="pptx")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"):
            request = PresentationExportRequest(
                self.source, self.root, "markdown", "reveal", "html", options={"execute": True}
            )
            with self.assertRaisesRegex(PresentationError, "options"):
                self.engine.presentations.export(request)

    def test_refuses_build_symlink_escape_and_unsupported_source(self):
        self.engine.create_file(self.project, "theory.tex", "\\documentclass{beamer}")
        with self.assertRaises(UnsupportedFileTypeError):
            self.engine.presentation_export_capabilities(self.project, "theory.tex")
        outside = Path(self.temp.name) / "elsewhere"
        outside.mkdir()
        builds = self.root / "builds"
        builds.mkdir()
        (builds / "presentations").symlink_to(outside, target_is_directory=True)
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"):
            with self.assertRaisesRegex(PresentationError, "build directory"):
                self.engine.export_presentation(self.project, "talk.slides.md", renderer_id="powerpoint", output_format="pptx")
        self.assertEqual(list(outside.iterdir()), [])

    def test_quarto_errors_and_missing_output_are_reported(self):
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "invalid source")):
            with self.assertRaisesRegex(PresentationError, "invalid source"):
                self.engine.export_presentation(self.project, "talk.slides.md", renderer_id="reveal", output_format="html")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            with self.assertRaisesRegex(PresentationError, "without producing"):
                self.engine.export_presentation(self.project, "talk.slides.md", renderer_id="reveal", output_format="html")


@unittest.skipUnless(importlib.util.find_spec("flask") is not None, "Flask is not installed")
class SharedPresentationHttpTests(unittest.TestCase):
    def setUp(self):
        import importlib
        self.web = importlib.import_module("tech_documents.web.app")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original_engine = self.web.engine
        self.web.engine = DocumentEngine(Path(self.temp.name) / "workspace")
        self.project = self.web.engine.create_project("demo")
        self.web.engine.create_file(self.project, "talk.slides.md", "# Talk")
        self.client = self.web.app.test_client()

    def tearDown(self):
        self.web.engine.notebooks.shutdown_all()
        self.web.engine = self.original_engine

    def test_markdown_exports_endpoint_and_capability_inspection(self):
        base = f"/api/presentations/{self.project}/talk.slides.md/exports"
        response = self.client.get(base)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["source_kind"], "markdown")
        self.assertEqual(len(response.get_json()["renderers"]), 3)
        with patch.object(self.web.engine.notebook_exports, "_quarto", return_value="quarto"):
            def complete(args, **kwargs):
                destination = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"test")
                return subprocess.CompletedProcess(args, 0, "", "")
            with patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=complete):
                response = self.client.post(base, json={"renderer": "powerpoint", "format": "pptx", "output_name": "slides"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["path"], "builds/presentations/slides.pptx")
        self.assertIn("download_url", data)
        response = self.client.post(base, json={"renderer": "Unknown", "format": "pdf"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
