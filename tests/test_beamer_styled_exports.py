"""PS-05: apply a pinned imported Beamer style through the shared export API."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tech_documents import DocumentEngine
from tech_documents.presentations import PresentationError, StyleReference
from tech_documents.presentations.beamer_rendering import stage_beamer_style


class StyledBeamerExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.engine = DocumentEngine(self.base / "workspace")
        self.project = self.engine.create_project("talk")
        self.root = self.engine.project_path(self.project)
        self.engine.create_file(self.project, "new.slides.md", "# Independent content\n\n## Diagram\n")
        self.engine.create_file(self.project, "stored.ipynb")
        self.source = self.root / "new.slides.md"
        self.theme_dir = self.base / "local-theme"
        (self.theme_dir / "pictures").mkdir(parents=True)
        (self.theme_dir / "beamerthemeMSU.sty").write_text(
            r"\mode<presentation>\RequirePackage{tikz}", encoding="utf-8",
        )
        (self.theme_dir / "beamercolorthemeMSU.sty").write_text("% blue\n", encoding="utf-8")
        (self.theme_dir / "pictures" / "logo.png").write_bytes(b"logo")
        self.install("1")
        self.ref = StyleReference("msu", "1", "beamer")

    def install(self, version):
        self.engine.presentation_styles.install(
            identifier="msu", version=version, kind="beamer", label="MSU",
            renderer_ids=("beamer",), source_dir=self.theme_dir,
            asset_paths=("beamerthemeMSU.sty", "beamercolorthemeMSU.sty", "pictures/logo.png"),
            entrypoint="beamerthemeMSU.sty",
        )

    def fake_render(self, args, *, cwd, env, **kwargs):
        self.assertEqual(cwd, str(Path(args[2]).parent))
        self.assertEqual(args[1], "render")
        self.assertIn("--no-execute", args)
        self.assertEqual(args[args.index("--to") + 1], "beamer")
        self.assertEqual(args[args.index("-M") + 1], "theme:MSU")
        self.assertNotIn("--execute", args)
        self.assertEqual(kwargs["check"], False)
        staged_root = Path(env["TEXINPUTS"].split(os.pathsep)[0][:-2])
        self.assertTrue((staged_root / "beamerthemeMSU.sty").is_file())
        self.assertEqual((staged_root / "pictures" / "logo.png").read_bytes(), b"logo")
        self.assertNotEqual(staged_root, self.engine.presentation_styles.root)
        self.staged.append(staged_root)
        dest = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4\n")
        return subprocess.CompletedProcess(args, 0, "", "")

    def test_styled_markdown_export_is_pinned_and_does_not_change_source(self):
        before = self.source.read_bytes()
        self.staged = []
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=self.fake_render):
            capabilities = self.engine.presentation_renderer_capabilities()
            self.assertIn("beamer", next(item for item in capabilities if item["id"] == "beamer")["style_kinds"])
            result = self.engine.export_presentation(
                self.project, "new.slides.md", renderer_id="beamer",
                output_format="pdf", style=self.ref, output_name="styled.pdf",
            )
        self.assertEqual(result["path"], "builds/presentations/styled.pdf")
        self.assertEqual(result["style"], {"identifier": "msu", "version": "1", "kind": "beamer"})
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(len(self.staged), 1)
        self.assertFalse(self.staged[0].exists(), "Build staging folder must be removed")
        self.assertTrue((self.root / result["path"]).is_file())

    def test_styled_notebook_export_uses_quarto_without_executing_cells(self):
        source = self.root / "stored.ipynb"
        original = source.read_bytes()
        self.staged = []
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True), \
             patch.object(self.engine.notebook_exports, "export", side_effect=AssertionError("must bypass legacy")), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=self.fake_render):
            result = self.engine.export_presentation(
                self.project, "stored.ipynb", renderer_id="beamer",
                output_format="pdf", style=self.ref,
            )
        self.assertEqual(result["path"], "builds/notebooks/stored.pdf")
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(self.staged[0].exists())

    def test_version_pinning_and_registry_integrity(self):
        self.install("2")
        (self.theme_dir / "beamerthemeMSU.sty").write_text("% changed source\n", encoding="utf-8")
        with stage_beamer_style(self.engine.presentation_styles, self.ref) as staged:
            root = Path(staged.environ["TEXINPUTS"].split(os.pathsep)[0][:-2])
            self.assertIn("tikz", (root / "beamerthemeMSU.sty").read_text(encoding="utf-8"))
        original = self.engine.presentation_styles.resolve(self.ref)
        original.asset("beamerthemeMSU.sty").write_text("% tampered", encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "integrity"):
            with stage_beamer_style(self.engine.presentation_styles, self.ref):
                pass

    def test_rejects_missing_unsupported_and_incomplete_style(self):
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True):
            with self.assertRaisesRegex(PresentationError, "not installed"):
                self.engine.export_presentation(self.project, "new.slides.md", renderer_id="beamer", output_format="pdf",
                                                style=StyleReference("absent", "1", "beamer"))
            with self.assertRaisesRegex(PresentationError, "does not support"):
                self.engine.export_presentation(self.project, "new.slides.md", renderer_id="powerpoint", output_format="pptx",
                                                style=self.ref)
            self.engine.presentation_styles.install(identifier="blank", version="1", kind="beamer", label="Blank",
                                                    renderer_ids=("beamer",))
            with self.assertRaisesRegex(PresentationError, "entrypoint"):
                self.engine.export_presentation(self.project, "new.slides.md", renderer_id="beamer", output_format="pdf",
                                                style=StyleReference("blank", "1", "beamer"))

    def test_error_cleanup_and_no_export_outside_project(self):
        self.staged = []
        def failing(args, *, env, **kwargs):
            staged_root = Path(env["TEXINPUTS"].split(os.pathsep)[0][:-2])
            self.staged.append(staged_root)
            return subprocess.CompletedProcess(args, 1, "", "Missing LaTeX package")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=failing):
            with self.assertRaisesRegex(PresentationError, "Missing LaTeX package"):
                self.engine.export_presentation(self.project, "new.slides.md", renderer_id="beamer", output_format="pdf",
                                                style=self.ref)
        self.assertFalse(self.staged[0].exists())
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "builds" / "presentations").rename(self.root / "builds" / "previous")
        (self.root / "builds" / "presentations").symlink_to(outside, target_is_directory=True)
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True):
            with self.assertRaisesRegex(PresentationError, "build directory"):
                self.engine.export_presentation(self.project, "new.slides.md", renderer_id="beamer", output_format="pdf",
                                                style=self.ref)
        self.assertEqual(list(outside.iterdir()), [])

    def test_stale_pdf_is_not_accepted_as_new_export(self):
        existing = self.root / "builds" / "presentations" / "new.pdf"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"older PDF")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, "", "")):
            with self.assertRaisesRegex(PresentationError, "without producing"):
                self.engine.export_presentation(
                    self.project, "new.slides.md", renderer_id="beamer", output_format="pdf", style=self.ref,
                )
        self.assertEqual(existing.read_bytes(), b"older PDF")
        self.assertEqual(list(existing.parent.glob(".beamer-output-*")), [])

    def test_fails_clearly_without_required_tools(self):
        with patch.object(self.engine.notebook_exports, "_quarto", return_value=None):
            with self.assertRaisesRegex(PresentationError, "Quarto|Install"):
                self.engine.export_presentation(self.project, "new.slides.md", renderer_id="beamer", output_format="pdf",
                                                style=self.ref)


@unittest.skipUnless(importlib.util.find_spec("flask") is not None, "Flask is not installed")
class StyledBeamerHttpTests(unittest.TestCase):
    def test_http_accepts_explicit_pinned_style_without_ui(self):
        from tech_documents.web import app as web
        with tempfile.TemporaryDirectory() as temp:
            old = web.engine
            try:
                web.engine = DocumentEngine(Path(temp) / "workspace")
                project = web.engine.create_project("demo")
                web.engine.create_file(project, "talk.md", "# Talk")
                base = f"/api/presentations/{project}/talk.md/exports"
                client = web.app.test_client()
                self.assertEqual(client.post(base, json={
                    "renderer": "beamer", "format": "pdf",
                    "style": {"identifier": "msu", "version": "1"},
                }).status_code, 400)
                self.assertEqual(client.post(base, json={
                    "renderer": "beamer", "format": "pdf",
                    "style": "bad",
                }).status_code, 400)
            finally:
                web.engine.notebooks.shutdown_all()
                web.engine = old


if __name__ == "__main__":
    unittest.main()
