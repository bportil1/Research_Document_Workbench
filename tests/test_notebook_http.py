from __future__ import annotations

import importlib.util
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec("flask") is not None, "Flask is not installed")
class NotebookHttpTests(unittest.TestCase):
    def setUp(self):
        import importlib

        web_module = importlib.import_module("tech_documents.web.app")
        self.web = web_module
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_engine = web_module.engine
        web_module.engine = self.original_engine.__class__(self.tempdir.name)
        self.project = web_module.engine.create_project("demo")
        web_module.engine.create_file(self.project, "analysis.ipynb")
        self.client = web_module.app.test_client()

    def tearDown(self):
        self.web.engine.notebooks.shutdown_all()
        self.web.engine = self.original_engine
        self.tempdir.cleanup()

    def test_notebook_read_save_and_kernel_status_routes(self):
        response = self.client.get(f"/api/notebooks/{self.project}/analysis.ipynb")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["notebook"]["nbformat"], 4)

        notebook = data["notebook"]
        notebook["cells"][0]["source"] = "# HTTP round trip"
        response = self.client.put(
            f"/api/notebooks/{self.project}/analysis.ipynb",
            json={"notebook": notebook},
        )
        self.assertEqual(response.status_code, 200)

        status = self.client.get(
            f"/api/notebooks/{self.project}/analysis.ipynb/kernel"
        ).get_json()
        self.assertIn("available", status)
        self.assertEqual(status["kernel"], "python3")

    @unittest.skipUnless(importlib.util.find_spec("nbconvert") is not None, "nbconvert is not installed")
    def test_notebook_export_capability_and_html_route(self):
        response = self.client.get(
            f"/api/notebooks/{self.project}/analysis.ipynb/exports"
        )
        self.assertEqual(response.status_code, 200)
        capabilities = response.get_json()
        html_format = next(item for item in capabilities["formats"] if item["id"] == "html")
        self.assertTrue(html_format["available"])

        response = self.client.post(
            f"/api/notebooks/{self.project}/analysis.ipynb/exports",
            json={"format": "html", "output_name": "presentation_test"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["path"], "builds/notebooks/presentation_test.html")
        self.assertIn("download_url", result)



if __name__ == "__main__":
    unittest.main()
