from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tech_documents" / "web" / "templates" / "index.html"
JAVASCRIPT = ROOT / "tech_documents" / "web" / "static" / "app.js"
STYLES = ROOT / "tech_documents" / "web" / "static" / "styles.css"


class NotebookPresentationFrontendContractTests(unittest.TestCase):
    def test_live_presentation_and_export_controls_are_present(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="notebookPresentBtn"', html)
        self.assertIn('id="notebookPresentation"', html)
        self.assertIn('id="notebookRevealSlides"', html)
        self.assertIn('id="notebookExportDialog"', html)
        self.assertIn('/static/vendor/reveal/dist/reveal.js', html)

    def test_standard_jupyter_slideshow_metadata_drives_live_deck(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('cell.metadata.slideshow.slide_type = role', javascript)
        self.assertIn('["slide", "New slide"]', javascript)
        self.assertIn('["subslide", "Sub-slide"]', javascript)
        self.assertIn('["fragment", "Fragment"]', javascript)
        self.assertIn('["skip", "Skip"]', javascript)
        self.assertIn('["notes", "Speaker notes"]', javascript)
        self.assertIn('new window.Reveal(notebookReveal', javascript)
        self.assertIn('Run live', javascript)
        self.assertIn('refreshNotebookPresentationCell(index)', javascript)

    def test_export_ui_is_preflighted_and_non_executing(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('Checking export capabilities', javascript)
        self.assertIn('/exports', javascript)
        self.assertIn('use stored outputs only', javascript)
        self.assertIn('format: selected.id', javascript)
        css = STYLES.read_text(encoding="utf-8")
        self.assertIn('.notebook-presentation', css)
        self.assertIn('.notebook-export-preflight', css)


if __name__ == "__main__":
    unittest.main()
