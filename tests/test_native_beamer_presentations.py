"""PS-10: direct native Beamer projects through the shared presentation service."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tech_documents.api import DocumentEngine
from tech_documents.compilation import CompilationResult
from tech_documents.errors import UnsupportedFileTypeError
from tech_documents.presentations import (
    PresentationError, StyleReference, discover_beamer_entrypoints, is_beamer_source,
)


class NativeBeamerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = DocumentEngine(Path(self.tmp.name) / "workbench")
        self.addCleanup(self.engine.notebooks.shutdown_all)
        self.project = self.engine.create_project("talks")
        self.root = self.engine.project_path(self.project)
        (self.root / "slides").mkdir()
        (self.root / "slides" / "main.tex").write_text(
            "\\documentclass[aspectratio=169]{beamer}\n"
            "\\usetheme{Nested}\n\\begin{document}\n"
            "\\begin{frame}{Hello}Hello project\\end{frame}\n"
            "\\end{document}\n", encoding="utf-8",
        )
        (self.root / "themes" / "deep").mkdir(parents=True)
        (self.root / "themes" / "deep" / "beamerthemeNested.sty").write_text(
            "\\ProvidesPackage{beamerthemeNested}\n"
            "\\mode<presentation>{\\setbeamertemplate{navigation symbols}{}}\n",
            encoding="utf-8",
        )
        (self.root / "slides" / "chapter.tex").write_text("\\begin{frame}Fragment\\end{frame}", encoding="utf-8")
        (self.root / "plain.tex").write_text("\\documentclass{article}\n", encoding="utf-8")

    def test_detection_distinguishes_main_fragments_and_comments(self):
        self.assertTrue(is_beamer_source("% \\documentclass{beamer}\n\\documentclass[12pt]{beamer}"))
        self.assertFalse(is_beamer_source("% \\documentclass{beamer}\n\\documentclass{article}"))
        self.assertFalse(is_beamer_source("\\% \\documentclass{article}"))
        self.assertEqual(self.engine.native_beamer_entrypoints(self.project), ["slides/main.tex"])
        with self.assertRaises(UnsupportedFileTypeError):
            self.engine.presentation_export_capabilities(self.project, "plain.tex")
        with self.assertRaises(UnsupportedFileTypeError):
            self.engine.presentation_export_capabilities(self.project, "slides/chapter.tex")

    def test_capabilities_native_without_quarto_or_notebook_runtime(self):
        with patch.object(self.engine.notebook_exports, "_quarto", return_value=None):
            info = self.engine.presentation_export_capabilities(self.project, "slides/main.tex")
        self.assertEqual(info["source_kind"], "latex")
        self.assertEqual([out["id"] for out in info["outputs"]], ["beamer:pdf"])
        self.assertEqual(info["outputs"][0]["style_kinds"], [])
        self.assertEqual(info["outputs"][0]["available"], bool(shutil.which("latexmk") or shutil.which("tectonic")))

    def test_local_theme_and_class_files_remain_editable_without_conversion(self):
        theme = "themes/deep/beamerthemeNested.sty"
        original = self.engine.read_file(self.project, theme)["content"]
        self.assertIn("ProvidesPackage", original)
        self.engine.save_file(self.project, theme, original + "% local customization\n")
        self.assertIn("local customization", self.engine.read_file(self.project, theme)["content"])
        (self.root / "themes/deep/local.cls").write_text("% local class", encoding="utf-8")
        self.assertEqual(self.engine.read_file(self.project, "themes/deep/local.cls")["content"], "% local class")

    def test_native_beamer_pdf_export_via_service_and_saved_profile(self):
        original = (self.root / "slides/main.tex").read_bytes()
        pdf = Path(self.tmp.name) / "compiled.pdf"
        pdf.write_bytes(b"%PDF-1.4\nhello\n")
        native = next(r for r in self.engine.presentations._renderers.values() if r.renderer_id == "beamer")
        with patch.object(native, "native_compile", return_value=CompilationResult(True, 200, pdf_path=pdf)) as compile_fn, \
             patch("tech_documents.presentations.legacy_adapters.shutil.which", return_value="/usr/bin/latexmk"):
            result = self.engine.export_presentation(self.project, "slides/main.tex", renderer_id="beamer", output_format="pdf", output_name="conference")
            self.assertEqual(result["path"], "builds/presentations/conference.pdf")
            self.assertEqual(result["source_kind"], "latex")
            self.assertEqual(result["engine"], "latex-native")
            self.assertEqual((self.root / result["path"]).read_bytes(), pdf.read_bytes())
            compile_fn.assert_called_once()
            profile = self.engine.save_presentation_profile(self.project, "slides/main.tex", renderer_id="beamer", output_format="pdf", output_name="saved")
            self.assertIsNone(profile["style"])
            saved = self.engine.export_presentation(self.project, "slides/main.tex", use_saved_profile=True)
            self.assertTrue(saved["saved_profile_applied"])
            self.assertTrue((self.root / saved["path"]).is_file())
        self.assertEqual((self.root / "slides/main.tex").read_bytes(), original)

    def test_same_basename_in_two_directories_exports_separately(self):
        (self.root / "other").mkdir()
        (self.root / "other" / "main.tex").write_text("\\documentclass{beamer}\n\\begin{document}\\end{document}", encoding="utf-8")
        compiled = Path(self.tmp.name) / "compiled.pdf"
        compiled.write_bytes(b"%PDF-1.4\n")
        native = self.engine.presentations._renderers["beamer"]
        with patch.object(native, "native_compile", return_value=CompilationResult(True, 200, pdf_path=compiled)), \
             patch("tech_documents.presentations.legacy_adapters.shutil.which", return_value="latexmk"):
            first = self.engine.export_presentation(self.project, "slides/main.tex", renderer_id="beamer", output_format="pdf")
            second = self.engine.export_presentation(self.project, "other/main.tex", renderer_id="beamer", output_format="pdf")
        self.assertNotEqual(first["path"], second["path"])
        self.assertTrue((self.root / first["path"]).is_file())
        self.assertTrue((self.root / second["path"]).is_file())

    def test_native_source_rejects_style_overlay_and_conversions(self):
        for options in (
            {"renderer_id":"powerpoint", "output_format":"pptx"},
            {"renderer_id":"beamer", "output_format":"pdf", "style": StyleReference("other", "1", "beamer")},
            {"conversion_target": "markdown"},
            {"document_format": "pdf"},
        ):
            with self.subTest(options=options), self.assertRaises(PresentationError):
                self.engine.export_presentation(self.project, "slides/main.tex", **options)
        with self.assertRaises(PresentationError):
            self.engine.save_presentation_profile(self.project, "slides/main.tex", renderer_id="beamer", output_format="pdf", style=StyleReference("other", "1", "beamer"))

    def test_native_export_rejects_symlinked_build_directory_before_compilation(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "builds").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.engine.export_presentation(self.project, "slides/main.tex", renderer_id="beamer", output_format="pdf")
        self.assertEqual(list(outside.iterdir()), [])

    def test_entrypoint_discovery_avoids_symlinks_and_build_outputs(self):
        (self.root / "builds").mkdir()
        (self.root / "builds" / "fake.tex").write_text("\\documentclass{beamer}")
        (self.root / "slides" / "linked.tex").symlink_to(self.root / "slides/main.tex")
        self.assertEqual(discover_beamer_entrypoints(self.root), ("slides/main.tex",))

    @unittest.skipUnless(shutil.which("latexmk"), "latexmk unavailable locally")
    def test_local_latexmk_builds_nested_theme_without_quarto(self):
        # Real compilation verifies TeX recursive search for theme files in
        # a nested local directory; neither Quarto nor remote services are used.
        original = (self.root / "slides/main.tex").read_bytes()
        with patch.object(self.engine.notebook_exports, "_quarto", return_value=None):
            output = self.engine.export_presentation(self.project, "slides/main.tex", renderer_id="beamer", output_format="pdf")
        result = self.root / output["path"]
        self.assertTrue(result.read_bytes().startswith(b"%PDF"))
        self.assertEqual((self.root / "slides/main.tex").read_bytes(), original)


@unittest.skipUnless(importlib.util.find_spec("flask"), "Flask unavailable")
class NativeBeamerApiTests(unittest.TestCase):
    def setUp(self):
        self.web = importlib.import_module("tech_documents.web.app")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = self.web.engine
        self.web.engine = DocumentEngine(self.tmp.name)
        self.addCleanup(setattr, self.web, "engine", self.old)
        self.addCleanup(self.web.engine.notebooks.shutdown_all)
        self.project = self.web.engine.create_project("demo")
        self.web.engine.create_file(self.project, "main.tex", "\\documentclass{beamer}\n")
        self.client = self.web.app.test_client()

    def test_discover_native_and_export_route(self):
        result = self.client.get(f"/api/presentations/{self.project}/native-beamer")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["entrypoints"], ["main.tex"])
        catalog = self.client.get(f"/api/presentations/{self.project}/main.tex/exports")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.get_json()["outputs"][0]["id"], "beamer:pdf")
        self.assertEqual(self.client.post(f"/api/presentations/{self.project}/main.tex/exports", json={"conversion_target":"notebook"}).status_code, 400)


class NativeBeamerFrontendContractTests(unittest.TestCase):
    def test_native_controls_and_editor_detection(self):
        repo = Path(__file__).resolve().parents[1]
        html = (repo / "tech_documents/web/templates/index.html").read_text(encoding="utf-8")
        js = (repo / "tech_documents/web/static/app.js").read_text(encoding="utf-8")
        for name in ("presentationNativeBuildBtn", "presentationFindNativeBtn", "presentationNativeMains"):
            self.assertIn(f'id="{name}"', html)
        self.assertIn("function isNativeBeamerSource(", js)
        self.assertIn("function buildNativeBeamerPresentation(", js)
        self.assertIn("function findNativeBeamerMains(", js)
        self.assertIn('currentPresentationKind()', js)
        self.assertIn('purposeOverride: "presentations"', js)

    def test_js_syntax(self):
        if not shutil.which("node"):
            self.skipTest("node unavailable")
        project = Path(__file__).resolve().parents[1]
        run = subprocess.run(["node", "--check", str(project / "tech_documents/web/static/app.js")], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
