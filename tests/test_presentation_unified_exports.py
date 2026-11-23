"""PS-08: source-specific export catalog and one engine dispatch boundary."""
from __future__ import annotations

from pathlib import Path
import importlib
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

from tech_documents.api import DocumentEngine
from tech_documents.presentations import PresentationError


class UnifiedPresentationExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = DocumentEngine(self.temp.name)
        self.addCleanup(self.engine.notebooks.shutdown_all)
        self.project = self.engine.create_project("talks")
        self.engine.create_file(self.project, "talk.slides.md", "# Hello\n\n---\n\n# Second")
        self.engine.create_file(self.project, "talk.ipynb")

    def test_markdown_catalog_is_source_specific(self):
        catalog = self.engine.presentation_export_capabilities(self.project, "talk.slides.md")
        by_id = {item["id"]: item for item in catalog["outputs"]}
        self.assertEqual(catalog["source_kind"], "markdown")
        self.assertEqual(set(by_id), {"beamer:pdf", "reveal:html", "powerpoint:pptx", "conversion:notebook"})
        self.assertEqual(by_id["conversion:notebook"]["kind"], "conversion")
        self.assertTrue(by_id["conversion:notebook"]["available"])
        self.assertEqual(by_id["conversion:notebook"]["style_kinds"], [])
        self.assertEqual(by_id["beamer:pdf"]["style_kinds"], ["beamer"])
        self.assertTrue(catalog["renderers"])  # PS-07 compatibility

    def test_markdown_render_availability_is_not_inherited_from_notebook(self):
        caps = self.engine.notebook_exports.capabilities()
        caps["quarto"] = False
        for item in caps["formats"]:
            if item["id"] in {"reveal", "pptx"}:
                item["available"] = True
                item["reason"] = ""
        with patch.object(self.engine.notebook_exports, "capabilities", return_value=caps):
            choices = {item["id"]: item for item in self.engine.presentation_export_capabilities(self.project, "talk.slides.md")["outputs"]}
        self.assertFalse(choices["reveal:html"]["available"])
        self.assertFalse(choices["powerpoint:pptx"]["available"])
        self.assertIn("Quarto", choices["powerpoint:pptx"]["reason"])

    def test_notebook_catalog_contains_original_document_formats(self):
        catalog = self.engine.presentation_export_capabilities(self.project, "talk.ipynb")
        choices = {item["id"]: item for item in catalog["outputs"]}
        self.assertEqual(catalog["source_kind"], "notebook")
        self.assertIn("conversion:markdown", choices)
        for format_id in ("html", "markdown", "docx", "pdf"):
            self.assertIn(f"document:{format_id}", choices)
        self.assertNotIn("document:beamer", choices)

    def test_markdown_to_notebook_uses_builds_and_does_not_change_source(self):
        source = self.engine.item_path(self.project, "talk.slides.md")
        original = source.read_text(encoding="utf-8")
        exported = self.engine.export_presentation(
            self.project, "talk.slides.md", conversion_target="notebook", output_name="conference",
        )
        self.assertEqual(exported["export_kind"], "conversion")
        self.assertEqual(exported["format"], "ipynb")
        self.assertEqual(exported["renderer"], "conversion")
        self.assertEqual(exported["engine"], "workbench-transfer")
        self.assertEqual(exported["path"], "builds/presentations/conference.ipynb")
        self.assertTrue((self.engine.project_path(self.project) / exported["path"]).is_file())
        self.assertEqual(source.read_text(encoding="utf-8"), original)
        self.assertIsNone(self.engine.presentation_profile(self.project, "talk.slides.md"))

    def test_notebook_to_slides_markdown_keeps_transfer_metadata(self):
        exported = self.engine.export_presentation(
            self.project, "talk.ipynb", conversion_target="markdown", output_name="conference"
        )
        self.assertEqual(exported["format"], "slides_md")
        self.assertEqual(exported["path"], "builds/presentations/conference.slides.md")
        self.assertIn("warnings", exported["details"])
        self.assertEqual(exported["source_kind"], "notebook")

    def test_document_format_uses_existing_notebook_exporter_without_execute(self):
        root = self.engine.project_path(self.project)
        destination = root / "builds" / "notebooks" / "notes.html"
        destination.parent.mkdir(parents=True)
        destination.write_text("OK", encoding="utf-8")
        fake_result = {"ok": True, "format": "html", "path": "builds/notebooks/notes.html", "size": 2, "engine": "nbconvert"}
        with patch.object(self.engine.notebook_exports, "export", return_value=fake_result) as exporter:
            result = self.engine.export_presentation(
                self.project, "talk.ipynb", document_format="html", output_name="notes"
            )
        self.assertEqual(result["export_kind"], "document")
        self.assertEqual(result["renderer"], "notebook-document")
        self.assertEqual(result["format"], "html")
        self.assertEqual(exporter.call_args.kwargs["format_id"], "html")
        self.assertEqual(exporter.call_args.kwargs["output_name"], "notes")

    def test_rejects_conflicting_or_incompatible_modes(self):
        for kwargs in (
            {"conversion_target": "markdown"},
            {"conversion_target": "notebook", "renderer_id": "beamer"},
            {"conversion_target": "notebook", "use_saved_profile": True},
            {"conversion_target": "notebook", "document_format": "html"},
            {"document_format": "html"},
            {"document_format": "beamer"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PresentationError):
                self.engine.export_presentation(self.project, "talk.slides.md", **kwargs)
        with self.assertRaises(PresentationError):
            self.engine.export_presentation(self.project, "talk.ipynb", document_format="reveal")

    def test_existing_pinned_profile_is_not_changed_by_conversion(self):
        self.engine.save_presentation_profile(
            self.project, "talk.slides.md", renderer_id="reveal", output_format="html", output_name="normal"
        )
        before = self.engine.presentation_profile(self.project, "talk.slides.md")
        self.engine.export_presentation(self.project, "talk.slides.md", conversion_target="notebook")
        self.assertEqual(self.engine.presentation_profile(self.project, "talk.slides.md"), before)

    def test_rejects_symlinked_build_and_output_destinations(self):
        root = self.engine.project_path(self.project)
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (root / "builds").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(Exception, "symlink"):
            self.engine.export_presentation(self.project, "talk.slides.md", conversion_target="notebook")
        self.assertEqual(list(outside.iterdir()), [])
        (root / "builds").unlink()
        destination = root / "builds" / "presentations"
        destination.mkdir(parents=True)
        (destination / "talk.ipynb").symlink_to(outside / "danger.ipynb")
        with self.assertRaisesRegex(Exception, "symlink"):
            self.engine.export_presentation(self.project, "talk.slides.md", conversion_target="notebook")
        self.assertFalse((outside / "danger.ipynb").exists())

    def test_markdown_long_extension_can_convert(self):
        self.engine.create_file(self.project, "long.markdown", "# Long")
        exported = self.engine.export_presentation(self.project, "long.markdown", conversion_target="notebook")
        self.assertTrue(exported["path"].endswith(".ipynb"))


@unittest.skipUnless(importlib.util.find_spec("flask"), "Flask not installed")
class UnifiedPresentationHttpTests(unittest.TestCase):
    def setUp(self):
        self.web = importlib.import_module("tech_documents.web.app")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original = self.web.engine
        self.web.engine = DocumentEngine(self.temp.name)
        self.addCleanup(setattr, self.web, "engine", self.original)
        self.addCleanup(self.web.engine.notebooks.shutdown_all)
        self.project = self.web.engine.create_project("demo")
        self.web.engine.create_file(self.project, "talk.slides.md", "# Hello")
        self.client = self.web.app.test_client()

    def test_unified_conversion_endpoint_and_download(self):
        url = f"/api/presentations/{self.project}/talk.slides.md/exports"
        options = self.client.get(url).get_json()["outputs"]
        self.assertTrue(any(entry["id"] == "conversion:notebook" for entry in options))
        made = self.client.post(url, json={"conversion_target": "notebook", "output_name": "backup"})
        self.assertEqual(made.status_code, 200, made.get_json())
        result = made.get_json()
        self.assertEqual(result["path"], "builds/presentations/backup.ipynb")
        self.assertEqual(self.client.get(result["download_url"]).status_code, 200)
        # Existing explicit conversion endpoint still works for adjacent backups.
        old = self.client.post(f"/api/presentations/{self.project}/talk.slides.md/convert", json={
            "target": "notebook", "location": "adjacent",
        })
        self.assertEqual(old.status_code, 200, old.get_json())

    def test_rejects_ambiguous_post_and_unknown_fields(self):
        url = f"/api/presentations/{self.project}/talk.slides.md/exports"
        for payload in (
            {"conversion_target": "notebook", "renderer": "beamer", "format": "pdf"},
            {"conversion_target": "notebook", "use_saved_profile": True},
            {"conversion_target": 7},
            {"document_format": "pdf"},
            {"unexpected": "field"},
        ):
            response = self.client.post(url, json=payload)
            self.assertNotEqual(response.status_code, 200, response.get_json())


if __name__ == "__main__":
    unittest.main()
