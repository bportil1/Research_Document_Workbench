"""PS-07: styling GUI and its local HTTP adapter contracts."""
from __future__ import annotations

from io import BytesIO
import importlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PresentationStyleUiContractTests(unittest.TestCase):
    def test_styling_controls_keep_existing_export_fallback(self):
        template = (ROOT / "tech_documents/web/templates/index.html").read_text(encoding="utf-8")
        js = (ROOT / "tech_documents/web/static/app.js").read_text(encoding="utf-8")
        css = (ROOT / "tech_documents/web/static/styles.css").read_text(encoding="utf-8")
        for control in (
            "presentationStyleBtn", "presentationStyleDialog", "presentationStyleRenderer",
            "presentationStyleSelection", "presentationStyleSaveBtn", "presentationStyleClearBtn",
            "presentationStyleExportBtn", "presentationStyleZip", "presentationStylePath",
            "presentationStyleInspectBtn", "presentationStyleCandidate", "presentationStyleImportBtn",
            "presentationStyleRemoveBtn", "presentationStyleImportStatus",
        ):
            self.assertIn(f'id="{control}"', template)
        self.assertIn('id="presentationExportBtn"', template)
        self.assertIn('id="notebookExportDialog"', template)
        self.assertIn('class="presentation-style-import"', template)
        self.assertIn('function refreshPresentationStyleSelection(', js)
        self.assertIn('function openPresentationStyleDialog(', js)
        self.assertIn('function exportSelectedPresentationStyle(', js)
        self.assertIn('function inspectPresentationStyleSource(', js)
        self.assertIn('function importSelectedPresentationStyle(', js)
        self.assertIn('function uninstallSelectedPresentationStyle(', js)
        self.assertIn('method: "PUT"', js)
        self.assertIn('method: "DELETE"', js)
        self.assertIn('method: "POST"', js)
        self.assertIn('new FormData()', js)
        self.assertIn('.presentation-style-dialog', css)

    def test_javascript_syntax(self):
        from shutil import which
        if not which("node"):
            self.skipTest("node is not installed")
        result = subprocess.run(["node", "--check", str(ROOT / "tech_documents/web/static/app.js")],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(importlib.util.find_spec("flask"), "Flask not installed")
class PresentationStyleHttpTests(unittest.TestCase):
    def setUp(self):
        self.web = importlib.import_module("tech_documents.web.app")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.original = self.web.engine
        from tech_documents.api import DocumentEngine
        self.web.engine = DocumentEngine(self.temporary.name)
        self.addCleanup(setattr, self.web, "engine", self.original)
        self.addCleanup(self.web.engine.notebooks.shutdown_all)
        self.project = self.web.engine.create_project("demo")
        self.web.engine.create_file(self.project, "talk.slides.md", "# Talk")
        self.client = self.web.app.test_client()

    @staticmethod
    def archive():
        file = BytesIO()
        with zipfile.ZipFile(file, "w") as zip_stream:
            zip_stream.writestr("slides/beamerthemeExample.sty", "% theme")
            zip_stream.writestr("slides/logo.png", b"logo")
            zip_stream.writestr("slides/example.tex", r"\documentclass{beamer}\n\usetheme{Example}")
        file.seek(0)
        return file

    def test_inspect_import_catalog_and_remove_uploaded_zip(self):
        pre = self.client.get("/api/presentation-styles")
        self.assertEqual(pre.status_code, 200)
        self.assertEqual(pre.get_json()["styles"], [])
        inspected = self.client.post("/api/presentation-styles/inspect", data={"archive": (self.archive(), "example.zip")})
        self.assertEqual(inspected.status_code, 200, inspected.get_json())
        selector = inspected.get_json()["inspection"]["themes"][0]["selector"]
        installed = self.client.post("/api/presentation-styles/import", data={
            "archive": (self.archive(), "example.zip"), "selector": selector,
            "version": "1.0.0", "label": "My Example"
        })
        self.assertEqual(installed.status_code, 201, installed.get_json())
        style = installed.get_json()["style"]
        self.assertEqual(style["label"], "My Example")
        self.assertEqual(style["renderer_ids"], ["beamer"])
        self.assertEqual(len(self.client.get("/api/presentation-styles").get_json()["styles"]), 1)
        profile = self.client.put(f"/api/presentations/{self.project}/talk.slides.md/profile", json={
            "renderer": "beamer", "format": "pdf", "style": {k: style[k] for k in ("identifier", "version", "kind")}
        })
        self.assertEqual(profile.status_code, 200, profile.get_json())
        self.assertEqual(profile.get_json()["profile"]["style_manifest_sha256"].__len__(), 64)
        gone = self.client.delete(f'/api/presentation-styles/{style["kind"]}/{style["identifier"]}/{style["version"]}')
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(self.client.get("/api/presentation-styles").get_json()["styles"], [])

    def test_project_relative_folder_and_traversal_restrictions(self):
        theme = self.web.engine.project_path(self.project) / "themes"
        theme.mkdir()
        (theme / "beamerthemeLocal.sty").write_text("% theme", encoding="utf-8")
        inspected = self.client.post("/api/presentation-styles/inspect", json={"project": self.project, "path": "themes"})
        self.assertEqual(inspected.status_code, 200)
        self.assertEqual(inspected.get_json()["inspection"]["themes"][0]["theme_name"], "Local")
        installed = self.client.post("/api/presentation-styles/import", json={
            "project": self.project, "path": "themes", "version": "1.0.0"
        })
        self.assertEqual(installed.status_code, 201, installed.get_json())
        denied = self.client.post("/api/presentation-styles/inspect", json={"project": self.project, "path": "../"})
        self.assertNotEqual(denied.status_code, 200)
        bad_upload = self.client.post("/api/presentation-styles/inspect", data={"archive": (BytesIO(b"no"), "theme.txt")})
        self.assertNotEqual(bad_upload.status_code, 200)


if __name__ == "__main__":
    unittest.main()
