"""PS-12 UI/API contracts; HTTP behavior exercised when local Flask is installed."""
from __future__ import annotations

from io import BytesIO
import importlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

from tech_documents.api import DocumentEngine

ROOT = Path(__file__).resolve().parents[1]


class PresentationFamilyUiContracts(unittest.TestCase):
    def test_family_management_and_bundle_controls_are_present(self):
        html = (ROOT / "tech_documents/web/templates/index.html").read_text(encoding="utf-8")
        script = (ROOT / "tech_documents/web/static/app.js").read_text(encoding="utf-8")
        for name in (
            "presentationFamilySelection", "presentationFamilyUseBtn", "presentationFamilyCreateBtn",
            "presentationFamilyDeleteBtn", "presentationFamilyExportBtn", "presentationBundleFile",
            "presentationBundleImportBtn", "presentationBundleExportStyleBtn", "presentationFamilyStatus",
            "presentationFamilyPrimary", "presentationFamilyAccent", "presentationFamilyFont",
            "presentationFamilyBeamer", "presentationFamilyReveal", "presentationFamilyPowerpoint",
        ):
            self.assertIn(f'id="{name}"', html)
        self.assertIn("loadPresentationStyleFamilies", script)
        self.assertIn("usePresentationFamilyVariant", script)
        self.assertIn("importPresentationBundle", script)
        self.assertIn("/api/presentation-style-bundles/import", script)

    def test_javascript_syntax(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("Node.js is unavailable")
        completed = subprocess.run(["node", "--check", str(ROOT / "tech_documents/web/static/app.js")],
                                   capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)


@unittest.skipUnless(importlib.util.find_spec("flask"), "Local Flask is not installed")
class PresentationFamilyHttpTests(unittest.TestCase):
    def setUp(self):
        self.web = importlib.import_module("tech_documents.web.app")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = self.web.engine
        self.web.engine = DocumentEngine(Path(self.temp.name) / "main")
        self.addCleanup(setattr, self.web, "engine", self.old)
        self.addCleanup(self.web.engine.notebooks.shutdown_all)
        self.client = self.web.app.test_client()
        self.style = self.web.engine.presentation_styles.install(
            identifier="http.style", version="1", kind="beamer", label="HTTP style", renderer_ids=("beamer",),
        )

    def test_create_export_import_and_family_dependency(self):
        payload = {
            "identifier": "lab", "version": "1", "label": "Lab", "description": "",
            "branding": {"colors": {"primary": "#123456"}, "fonts": {"body": "Aptos"}},
            "variants": [{
                "renderer_id": "beamer", "style": {"identifier": "http.style", "version": "1", "kind": "beamer"},
                "branding": {"colors": {}, "fonts": {}}, "logo_asset": "",
            }],
        }
        response = self.client.post("/api/presentation-style-families", json=payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(len(self.client.get("/api/presentation-style-families").get_json()["families"]), 1)
        blocked = self.client.delete("/api/presentation-styles/beamer/http.style/1")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("remove that family first", blocked.get_json()["error"])
        package = self.client.get("/api/presentation-style-families/lab/1/bundle")
        self.assertEqual(package.status_code, 200)
        self.assertEqual(package.mimetype, "application/zip")
        other = DocumentEngine(Path(self.temp.name) / "other")
        self.web.engine = other
        result = self.client.post("/api/presentation-style-bundles/import",
                                  data={"archive": (BytesIO(package.data), "portable.zip")},
                                  content_type="multipart/form-data")
        self.assertEqual(result.status_code, 201, result.get_json())
        self.assertEqual(result.get_json()["family"]["identifier"], "lab")
        self.assertEqual(len(other.presentation_style_family_catalog()), 1)

    def test_invalid_package_import_rejected(self):
        result = self.client.post("/api/presentation-style-bundles/import",
                                  data={"archive": (BytesIO(b"not a zip"), "bundle.zip")},
                                  content_type="multipart/form-data")
        self.assertEqual(result.status_code, 400)
        self.assertFalse(result.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
