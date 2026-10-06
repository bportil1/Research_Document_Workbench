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
        self.assertIn('id="presentationPresentBtn"', html)
        self.assertIn('id="presentationExportBtn"', html)
        self.assertIn('id="notebookPresentation"', html)
        self.assertIn('id="notebookRevealSlides"', html)
        self.assertIn('id="notebookExportDialog"', html)
        self.assertIn('/static/vendor/reveal/dist/reveal.js', html)

    def test_markdown_cells_default_to_slides_and_metadata_overrides_remain_supported(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function notebookStoredSlideRole(cell)', javascript)
        self.assertIn('return cell?.cell_type === "markdown" ? "slide" : "";', javascript)
        self.assertIn('if (role === "slide")', javascript)
        self.assertIn('cell.metadata.slideshow.slide_type = role', javascript)
        self.assertIn('["slide", "Slide"]', javascript)
        self.assertIn('["subslide", "Sub-slide"]', javascript)
        self.assertIn('["fragment", "Fragment"]', javascript)
        self.assertIn('["skip", "Skip"]', javascript)
        self.assertIn('["notes", "Speaker notes"]', javascript)
        self.assertIn('if (cell.cell_type === "markdown" && workbenchPurpose === "presentations") {\n    actions.appendChild(notebookSlideRoleSelect(cell, index));', javascript)
        self.assertIn('new window.Reveal(notebookReveal', javascript)
        self.assertIn('Run live', javascript)
        self.assertIn('refreshNotebookPresentationCell(index)', javascript)


    def test_presentation_controls_are_isolated_in_a_first_class_subwing(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="workbenchPurposeBar"', html)
        self.assertIn('id="documentsPurposeBtn"', html)
        self.assertIn('id="presentationsPurposeBtn"', html)
        self.assertIn('id="presentationToolbar"', html)
        self.assertIn('id="presentationKindLabel"', html)
        self.assertNotIn('id="notebookPresentBtn"', html)
        self.assertNotIn('id="notebookExportBtn"', html)

        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function setWorkbenchPurpose(purpose, { announce = true } = {})', javascript)
        self.assertIn('function currentPresentationKind()', javascript)
        self.assertIn('"Notebook Presentation"', javascript)
        self.assertIn('"Markdown Presentation"', javascript)
        self.assertIn('isPresentationMarkdownPath(currentFile)', javascript)
        self.assertIn('workbenchPurpose === "presentations"', javascript)

        css = STYLES.read_text(encoding="utf-8")
        self.assertIn('.workbench-purpose-bar', css)
        self.assertIn('.presentation-toolbar', css)

    def test_notebook_authoring_preview_is_side_by_side_collapsible_and_synchronized(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="notebookAuthoring"', html)
        self.assertIn('id="notebookSlidePreviewPane"', html)
        self.assertIn('id="notebookPreviewResizer"', html)
        self.assertIn('id="notebookSlidePreviewCanvas"', html)

        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function setNotebookSlidePreviewVisible(visible)', javascript)
        self.assertIn('function renderNotebookSlidePreview()', javascript)
        self.assertIn('function notebookSlidePreviewEntries(index)', javascript)
        self.assertIn('if (workbenchPurpose === "presentations") toggleNotebookSlidePreview();', javascript)
        self.assertIn('renderNotebookSlidePreview();', javascript)
        self.assertIn('NOTEBOOK_PREVIEW_WIDTH_STORAGE_KEY', javascript)

        css = STYLES.read_text(encoding="utf-8")
        self.assertIn('.editor-grid[hidden]', css)
        self.assertIn('.notebook-authoring', css)
        self.assertIn('.notebook-slide-preview-pane', css)
        self.assertIn('.notebook-preview-resizer', css)
        self.assertIn('.notebook-slide-preview-canvas', css)

    def test_standalone_markdown_presentations_are_native_and_explicit(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('data-file-action="open-document"', html)
        self.assertIn('data-file-action="open-presentation"', html)

        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function splitPresentationMarkdown(source)', javascript)
        self.assertIn('/^\\s*---\\s*$/.test(line)', javascript)
        self.assertIn('function buildMarkdownPresentationSlides()', javascript)
        self.assertIn('function openMarkdownPresentation()', javascript)
        self.assertIn('renderPresentationModelSlides(buildMarkdownPresentationModel(editor.value))', javascript)
        self.assertIn('Standalone Markdown · local Reveal.js · --- separates slides', javascript)
        self.assertIn('openFile(item.path, { purposeOverride: "documents" })', javascript)
        self.assertIn('openFile(item.path, { purposeOverride: "presentations" })', javascript)
        self.assertIn('isPresentationMarkdownPath(currentFile)', javascript)
        self.assertIn('markdownReady', javascript)
        self.assertIn('openMarkdownPresentation().catch', javascript)


    def test_notebook_and_markdown_share_one_internal_presentation_model(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function createPresentationModel(sourceKind)', javascript)
        self.assertIn('function buildNotebookPresentationModel()', javascript)
        self.assertIn('function buildMarkdownPresentationModel(source = editor.value)', javascript)
        self.assertIn('function currentPresentationModel()', javascript)
        self.assertIn('function renderPresentationModelSlides(model)', javascript)
        self.assertIn('function renderPresentationSlide(slide, container)', javascript)
        self.assertIn('function findPresentationItemLocation(model, predicate)', javascript)
        self.assertIn('renderPresentationSlide(location.slide, notebookSlidePreviewCanvas)', javascript)
        self.assertIn('function renderMarkdownPresentationPreview()', javascript)
        self.assertIn('renderPresentationSlide(slide, markdownPreview)', javascript)
        self.assertIn('buildCurrentPresentationSlides();', javascript)
        self.assertIn('role === "fragment"', javascript)
        self.assertIn('role === "notes"', javascript)


    def test_presentation_cross_transfer_uses_existing_export_surface(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function openPresentationTransferDialog()', javascript)
        self.assertIn('workbench-presentation-markdown', javascript)
        self.assertIn('workbench-presentation-notebook', javascript)
        self.assertIn('/api/presentations/', javascript)
        self.assertIn('builds/presentations/', javascript)
        self.assertIn('presentationExportBtn.disabled = !(notebookReady || markdownReady);', javascript)

    def test_presentation_backup_and_export_workflow_is_explicit_and_paired(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="presentationBackupBtn"', html)
        self.assertIn('id="presentationExportTitle"', html)
        self.assertIn('id="presentationExportSubtitle"', html)

        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function createPresentationBackup()', javascript)
        self.assertIn('location: "adjacent"', javascript)
        self.assertIn('location: "build"', javascript)
        self.assertIn('function renderPresentationTransferResult(result', javascript)
        self.assertIn('presentation-export-warnings', javascript)
        self.assertIn('openPresentationTransferDialog().catch', javascript)
        self.assertIn('Presentation · Workbench Markdown (.slides.md)', javascript)
        self.assertIn('Presentation · Notebook (.ipynb)', javascript)

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
