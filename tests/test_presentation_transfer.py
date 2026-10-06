from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tech_documents.api import DocumentEngine


class PresentationTransferTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.engine = DocumentEngine(self.tempdir.name)
        self.project = self.engine.create_project("demo")

    def tearDown(self):
        self.engine.notebooks.shutdown_all()
        self.tempdir.cleanup()

    def test_notebook_to_markdown_backup_preserves_slide_roles_and_static_code(self):
        self.engine.create_file(self.project, "talk.ipynb")
        data = self.engine.read_notebook(self.project, "talk.ipynb")["notebook"]
        data["cells"] = [
            {"cell_type":"markdown","id":"a","metadata":{},"source":"# One"},
            {"cell_type":"markdown","id":"b","metadata":{"slideshow":{"slide_type":"subslide"}},"source":"## Two"},
            {"cell_type":"code","id":"c","metadata":{},"source":"print('x')","execution_count":1,"outputs":[{"output_type":"stream","name":"stdout","text":"x\\n"}]},
        ]
        self.engine.save_notebook(self.project, "talk.ipynb", data)
        result = self.engine.convert_presentation(self.project, "talk.ipynb", target="markdown")
        output = self.engine.project_path(self.project) / result["path"]
        text = output.read_text(encoding="utf-8")
        self.assertIn("format: workbench-slides", text)
        self.assertIn("workbench-slide-role: slide", text)
        self.assertIn("workbench-slide-role: subslide", text)
        self.assertIn("```python", text)
        self.assertIn("```text", text)
        self.assertEqual(result["details"]["static_outputs"], 1)

    def test_markdown_to_notebook_round_trip_restores_supported_roles(self):
        self.engine.create_file(self.project, "talk.slides.md", """---\npresentation: true\n---\n\n<!-- workbench-slide-role: slide -->\n\n# One\n\n---\n\n<!-- workbench-slide-role: fragment -->\n\nMore\n""")
        result = self.engine.convert_presentation(self.project, "talk.slides.md", target="notebook")
        path = self.engine.project_path(self.project) / result["path"]
        import nbformat
        nb = nbformat.read(path, as_version=4)
        self.assertEqual(len(nb.cells), 2)
        self.assertEqual(nb.cells[0].metadata.slideshow.slide_type, "slide")
        self.assertEqual(nb.cells[1].metadata.slideshow.slide_type, "fragment")
        self.assertEqual(nb.cells[0].source, "# One")
