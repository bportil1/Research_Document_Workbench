from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tech_documents" / "web" / "templates" / "index.html"
JAVASCRIPT = ROOT / "tech_documents" / "web" / "static" / "app.js"
STYLES = ROOT / "tech_documents" / "web" / "static" / "styles.css"


class NotebookFrontendContractTests(unittest.TestCase):
    def test_notebook_has_structured_surface_and_python_controls(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="notebookWorkspace"', html)
        self.assertIn('id="notebookCells"', html)
        self.assertIn('id="notebookRunAllBtn"', html)
        self.assertIn('id="notebookInterruptBtn"', html)
        self.assertIn('id="notebookRestartBtn"', html)
        self.assertIn('id="newNotebookBtn"', html)
        self.assertIn('/static/vendor/ace/ace.js', html)

    def test_ipynb_uses_notebook_api_and_not_text_editor_json(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function isNotebookPath(path)', javascript)
        self.assertIn('await openNotebook(filename)', javascript)
        self.assertIn('/api/notebooks/', javascript)
        self.assertIn('window.ace.edit(host)', javascript)
        self.assertIn('runNotebookCell(index, true)', javascript)
        self.assertIn('application/json', javascript)
        self.assertIn('image/svg+xml', javascript)

    def test_notebook_styles_are_scoped(self):
        css = STYLES.read_text(encoding="utf-8")
        self.assertIn('.notebook-workspace', css)
        self.assertIn('.notebook-cell', css)
        self.assertIn('.notebook-output', css)
        self.assertIn('.notebook-markdown-rendered', css)


if __name__ == "__main__":
    unittest.main()
