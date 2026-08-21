from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

from tech_documents import DocumentEngine, UnsupportedFileTypeError


NOTEBOOK_RUNTIME_AVAILABLE = all(
    importlib.util.find_spec(name) is not None
    for name in ("nbformat", "jupyter_client", "ipykernel")
)


class NotebookEngineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.engine = DocumentEngine(self.tempdir.name)
        self.project = self.engine.create_project("notebook_demo")

    def tearDown(self):
        self.engine.notebooks.shutdown_all()
        self.tempdir.cleanup()

    @unittest.skipUnless(NOTEBOOK_RUNTIME_AVAILABLE, "Jupyter notebook dependencies are not installed")
    def test_create_read_save_notebook_round_trip_preserves_metadata(self):
        path = self.engine.create_file(self.project, "analysis.ipynb")
        self.assertEqual(path, "analysis.ipynb")

        result = self.engine.read_notebook(self.project, path)
        notebook = result["notebook"]
        self.assertEqual(notebook["nbformat"], 4)
        self.assertEqual([cell["cell_type"] for cell in notebook["cells"]], ["markdown", "code"])
        self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "python3")

        notebook["metadata"]["custom_workflow"] = {"keep": True}
        notebook["cells"][0]["metadata"]["custom_cell_key"] = "preserved"
        notebook["cells"][0]["attachments"] = {
            "tiny.txt": {"text/plain": "attachment payload"}
        }
        notebook["cells"][0]["source"] = "# Updated notebook"
        notebook["cells"].append({
            "cell_type": "raw",
            "id": "rawcell1",
            "metadata": {"format": "text/plain"},
            "source": "preserve raw source",
        })
        self.engine.save_notebook(self.project, path, notebook)

        reopened = self.engine.read_notebook(self.project, path)["notebook"]
        self.assertEqual(reopened["metadata"]["custom_workflow"], {"keep": True})
        self.assertEqual(reopened["cells"][0]["metadata"]["custom_cell_key"], "preserved")
        self.assertEqual(
            reopened["cells"][0]["attachments"]["tiny.txt"]["text/plain"],
            "attachment payload",
        )
        self.assertEqual(reopened["cells"][0]["source"], "# Updated notebook")
        self.assertEqual(reopened["cells"][-1]["cell_type"], "raw")
        self.assertEqual(reopened["cells"][-1]["source"], "preserve raw source")

    @unittest.skipUnless(NOTEBOOK_RUNTIME_AVAILABLE, "Jupyter notebook dependencies are not installed")
    def test_notebook_export_capabilities_validate_existing_notebook(self):
        path = self.engine.create_file(self.project, "analysis.ipynb")
        capabilities = self.engine.notebook_export_capabilities(self.project, path)
        self.assertIn("formats", capabilities)

    @unittest.skipUnless(NOTEBOOK_RUNTIME_AVAILABLE, "Jupyter notebook dependencies are not installed")
    def test_notebook_uses_structured_api_not_text_api(self):
        self.engine.create_file(self.project, "analysis.ipynb")
        with self.assertRaises(UnsupportedFileTypeError):
            self.engine.read_file(self.project, "analysis.ipynb")
        with self.assertRaises(UnsupportedFileTypeError):
            self.engine.save_file(self.project, "analysis.ipynb", "{}")

    @unittest.skipUnless(NOTEBOOK_RUNTIME_AVAILABLE, "Jupyter notebook dependencies are not installed")
    def test_python_kernel_is_persistent_and_restart_resets_state(self):
        path = self.engine.create_file(self.project, "analysis.ipynb")
        first = self.engine.execute_notebook_cell(
            self.project,
            path,
            "value = 41\nvalue + 1",
        )
        self.assertTrue(first["kernel"]["running"])
        self.assertEqual(first["outputs"][-1]["output_type"], "execute_result")
        self.assertEqual(first["outputs"][-1]["data"]["text/plain"], "42")

        second = self.engine.execute_notebook_cell(self.project, path, "value + 2")
        self.assertEqual(second["outputs"][-1]["data"]["text/plain"], "43")

        project_file = self.engine.project_path(self.project) / "relative.txt"
        project_file.write_text("project-relative", encoding="utf-8")
        relative = self.engine.execute_notebook_cell(
            self.project,
            path,
            "from pathlib import Path; Path('relative.txt').read_text()",
        )
        self.assertEqual(relative["outputs"][-1]["data"]["text/plain"], "'project-relative'")

        restarted = self.engine.restart_notebook_kernel(self.project, path)
        self.assertTrue(restarted["running"])
        third = self.engine.execute_notebook_cell(
            self.project,
            path,
            "globals().get('value', 'missing')",
        )
        self.assertEqual(third["outputs"][-1]["data"]["text/plain"], "'missing'")

    @unittest.skipUnless(NOTEBOOK_RUNTIME_AVAILABLE, "Jupyter notebook dependencies are not installed")
    def test_notebook_execution_captures_stream_and_error_outputs(self):
        path = self.engine.create_file(self.project, "analysis.ipynb")
        stream = self.engine.execute_notebook_cell(self.project, path, "print('hello notebook')")
        self.assertEqual(stream["outputs"][0]["output_type"], "stream")
        self.assertIn("hello notebook", stream["outputs"][0]["text"])

        failure = self.engine.execute_notebook_cell(self.project, path, "raise ValueError('boom')")
        self.assertEqual(failure["outputs"][-1]["output_type"], "error")
        self.assertEqual(failure["outputs"][-1]["ename"], "ValueError")
        self.assertIn("boom", failure["outputs"][-1]["evalue"])

    def test_ipynb_is_exposed_as_editable_project_document(self):
        project_path = self.engine.project_path(self.project)
        (project_path / "external.ipynb").write_text(
            '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}',
            encoding="utf-8",
        )
        listed = self.engine.list_projects()[0]
        record = next(item for item in listed["files"] if item["path"] == "external.ipynb")
        self.assertTrue(record["editable"])
        self.assertEqual(record["extension"], ".ipynb")


if __name__ == "__main__":
    unittest.main()
