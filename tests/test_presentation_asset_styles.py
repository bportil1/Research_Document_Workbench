"""PS-11: renderer-neutral asset styles, local-only import and styled exports."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tech_documents import DocumentEngine
from tech_documents.presentations import PresentationError, StyleReference


class PresentationAssetStyleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.engine = DocumentEngine(self.base / "workbench")
        self.project = self.engine.create_project("demo")
        self.root = self.engine.project_path(self.project)
        self.engine.create_file(self.project, "talk.slides.md", "# Title\n\n## Next slide\n")

    def make_css(self):
        folder = self.base / "reveal-style"
        (folder / "img").mkdir(parents=True)
        (folder / "bright.css").write_text(
            ".reveal { background-image: url('./img/back.svg'); color: #123; }\n",
            encoding="utf-8",
        )
        (folder / "img" / "back.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        return folder

    def make_pptx(self):
        # The importer supports a normal, real PowerPoint reference document.
        from pptx import Presentation
        file = self.base / "reference.pptx"
        deck = Presentation()
        deck.slides.add_slide(deck.slide_layouts[0])
        deck.save(file)
        return file

    def test_reveal_css_folder_import_version_and_assets(self):
        folder = self.make_css()
        inspection = self.engine.inspect_asset_styles(folder, kind="reveal")
        self.assertEqual(len(inspection["themes"]), 1)
        self.assertEqual(inspection["themes"][0]["selector"], "bright.css")
        before = (folder / "bright.css").read_bytes()
        manifest = self.engine.import_asset_style(folder, kind="reveal", version="1.0.0")
        self.assertEqual(manifest["kind"], "reveal")
        self.assertEqual(manifest["renderer_ids"], ["reveal"])
        self.assertEqual(manifest["entrypoint"], "bright.css")
        self.assertEqual({a["path"] for a in manifest["assets"]}, {"bright.css", "img/back.svg"})
        self.assertEqual((folder / "bright.css").read_bytes(), before)
        reference = StyleReference(manifest["identifier"], manifest["version"], "reveal")
        self.assertEqual(self.engine.presentation_styles.resolve(reference).manifest.as_dict(), manifest)
        self.assertEqual(len(self.engine.presentation_style_catalog(renderer_id="reveal")), 1)
        with self.assertRaises(PresentationError):
            self.engine.import_asset_style(folder, kind="reveal", version="1.0.0")

    def test_powerpoint_reference_file_import(self):
        path = self.make_pptx()
        inspection = self.engine.inspect_asset_styles(path, kind="powerpoint")
        self.assertEqual(inspection["themes"][0]["selector"], "reference.pptx")
        manifest = self.engine.import_asset_style(path, kind="powerpoint", version="2026.1")
        self.assertEqual(manifest["kind"], "powerpoint")
        self.assertEqual(manifest["entrypoint"], "reference.pptx")
        self.assertEqual(len(manifest["assets"]), 1)

    def test_zip_import_with_explicit_selector(self):
        folder = self.make_css()
        archive = self.base / "styles.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.write(folder / "bright.css", "themes/bright.css")
            z.write(folder / "img" / "back.svg", "themes/img/back.svg")
            z.writestr("themes/plain.css", "body { color: red; }")
        inspection = self.engine.inspect_asset_styles(archive, kind="reveal")
        self.assertEqual(len(inspection["themes"]), 2)
        with self.assertRaises(PresentationError):
            self.engine.import_asset_style(archive, kind="reveal", version="1")
        manifest = self.engine.import_asset_style(
            archive, kind="reveal", version="1", selector="themes/bright.css",
        )
        self.assertEqual(manifest["entrypoint"], "bright.css")
        self.assertEqual({a["path"] for a in manifest["assets"]}, {"bright.css", "img/back.svg", "plain.css"})

    def test_reject_remote_css_and_escape_and_missing_resources(self):
        folder = self.make_css()
        css = folder / "bright.css"
        for content in (
            '@import "https://cdn.example.org/theme.css";',
            'body { background: url(https://cdn.example.org/x.png); }',
            'body { background: url(../secret.svg); }',
            'body { background: url(img/unknown.svg); }',
        ):
            with self.subTest(content=content):
                css.write_text(content)
                with self.assertRaises(PresentationError):
                    self.engine.inspect_asset_styles(folder, kind="reveal")
        self.assertEqual(self.engine.presentation_style_catalog(), [])

    def test_reject_invalid_pptx(self):
        invalid = self.base / "not-a-pptx.pptx"
        invalid.write_bytes(b"not a powerpoint template")
        with self.assertRaises(PresentationError):
            self.engine.import_asset_style(invalid, kind="powerpoint", version="1")
        self.assertEqual(self.engine.presentation_style_catalog(), [])

    def test_reject_zip_traversal(self):
        archive = self.base / "bad.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../escape.css", "body{}")
        with self.assertRaises(PresentationError):
            self.engine.inspect_asset_styles(archive, kind="reveal")

    def test_reveal_and_pptx_styled_exports_via_same_service(self):
        reveal = self.engine.import_asset_style(self.make_css(), kind="reveal", version="1")
        powerpoint = self.engine.import_asset_style(self.make_pptx(), kind="powerpoint", version="1")
        original = (self.root / "talk.slides.md").read_bytes()

        def local_quarto(command, **kwargs):
            self.assertIn("--no-execute", command)
            self.assertIn("--metadata-file", command)
            metadata = json.loads(Path(command[command.index("--metadata-file") + 1]).read_text())
            if command[command.index("--to") + 1] == "revealjs":
                self.assertTrue(Path(metadata["format"]["revealjs"]["css"]).is_file())
                self.assertTrue(metadata["format"]["revealjs"]["embed-resources"])
            else:
                self.assertTrue(Path(metadata["format"]["pptx"]["reference-doc"]).is_file())
            outfile = Path(command[command.index("--output-dir") + 1]) / command[command.index("--output") + 1]
            outfile.write_bytes(b"rendered locally")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.object(self.engine.notebook_exports, "_quarto", return_value="/local/quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=local_quarto) as runner:
            for manifest, renderer, fmt in ((reveal, "reveal", "html"), (powerpoint, "powerpoint", "pptx")):
                result = self.engine.export_presentation(
                    self.project, "talk.slides.md", renderer_id=renderer, output_format=fmt,
                    style=StyleReference(manifest["identifier"], manifest["version"], renderer),
                )
                self.assertTrue((self.root / result["path"]).is_file())
                self.assertEqual(result["renderer"], renderer)
            self.assertEqual(runner.call_count, 2)
        self.assertEqual((self.root / "talk.slides.md").read_bytes(), original)

    def test_styled_notebook_and_saved_pptx_profile(self):
        self.engine.create_file(self.project, "deck.ipynb")
        manifest = self.engine.import_asset_style(self.make_pptx(), kind="powerpoint", version="1")
        reference = StyleReference(manifest["identifier"], "1", "powerpoint")
        saved = self.engine.save_presentation_profile(
            self.project, "deck.ipynb", renderer_id="powerpoint", output_format="pptx",
            output_name="named.pptx", style=reference,
        )
        self.assertEqual(saved["style"]["version"], "1")
        self.assertEqual(self.engine.presentation_profile(self.project, "deck.ipynb")["style"], saved["style"])

        def fake_render(command, **kwargs):
            self.assertIn("--no-execute", command)
            self.assertEqual(command[command.index("--to") + 1], "pptx")
            out = Path(command[command.index("--output-dir") + 1]) / command[command.index("--output") + 1]
            out.write_bytes(b"local pptx")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.object(self.engine.notebook_exports, "_quarto", return_value="/local/quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=fake_render):
            result = self.engine.export_presentation(self.project, "deck.ipynb", use_saved_profile=True)
        self.assertTrue(result["saved_profile_applied"])
        self.assertEqual(result["path"], "builds/notebooks/named.pptx")
        self.assertEqual(result["style"]["version"], "1")

    def test_reject_svg_external_links_and_pptx_external_relationships(self):
        folder = self.make_css()
        (folder / "img" / "back.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.org/img.png" /></svg>'
        )
        with self.assertRaisesRegex(PresentationError, "SVG style resources"):
            self.engine.inspect_asset_styles(folder, kind="reveal")
        from pptx import Presentation
        path = self.base / "remote.pptx"
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[0])
        run = slide.shapes.title.text_frame.paragraphs[0].add_run()
        run.text = "External"
        run.hyperlink.address = "https://example.org"
        deck.save(path)
        with self.assertRaisesRegex(PresentationError, "external resource relationships"):
            self.engine.inspect_asset_styles(path, kind="powerpoint")

    def test_mismatched_style_renderer_fails(self):
        reveal = self.engine.import_asset_style(self.make_css(), kind="reveal", version="1")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="/local/quarto"):
            with self.assertRaises(PresentationError):
                self.engine.export_presentation(
                    self.project, "talk.slides.md", renderer_id="powerpoint", output_format="pptx",
                    style=StyleReference(reveal["identifier"], "1", "reveal"),
                )


if __name__ == "__main__":
    unittest.main()
