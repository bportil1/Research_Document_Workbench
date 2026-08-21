from pathlib import Path
import unittest

from tech_documents.notebook_exports import NotebookExportService


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tech_documents" / "web" / "templates" / "index.html"
COMPAT = ROOT / "tech_documents" / "web" / "static" / "highlight_compat.js"


class NotebookHighlightCompatibilityTests(unittest.TestCase):
    def test_live_workbench_loads_highlight_guard_before_reveal_and_app(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        guard = html.index('/static/highlight_compat.js')
        reveal = html.index('/static/vendor/reveal/dist/reveal.js')
        app = html.index('/static/app.js')
        self.assertLess(guard, reveal)
        self.assertLess(guard, app)
        script = COMPAT.read_text(encoding="utf-8")
        self.assertIn("window.hljs", script)
        self.assertIn("highlightElement", script)

    def test_export_guard_is_inserted_before_document_scripts(self):
        service = NotebookExportService(static_root=ROOT / "tech_documents" / "web" / "static")
        html = '<html><head><script src="presentation.js"></script></head><body></body></html>'
        guarded = service._with_highlight_compatibility(html)
        self.assertIn("data-workbench-highlight-compat", guarded)
        self.assertLess(guarded.index("data-workbench-highlight-compat"), guarded.index("presentation.js"))


if __name__ == "__main__":
    unittest.main()
