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
        self.assertIn('id="presentationStyleBtn"', html)
        self.assertIn('id="notebookPresentation"', html)
        self.assertIn('id="notebookRevealSlides"', html)
        self.assertIn('id="presentationStyleDialog"', html)
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


    def test_presentation_cross_transfer_uses_unified_export_surface(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function presentationStyleRequestBody(', javascript)
        self.assertIn('conversion_target:', javascript)
        self.assertIn('document_format:', javascript)
        self.assertIn('presentationStyleUrl(session, "/exports")', javascript)
        self.assertIn('function showPresentationExportResult(result)', javascript)
        self.assertNotIn('function openPresentationTransferDialog()', javascript)
        self.assertNotIn('presentationExportBtn', javascript)

    def test_presentation_backup_and_export_workflow_is_explicit_and_paired(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('id="presentationBackupBtn"', html)
        self.assertIn('id="presentationStyleDialog"', html)
        self.assertIn('id="presentationStyleRenderer"', html)
        self.assertNotIn('id="notebookExportDialog"', html)

        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('function createPresentationBackup()', javascript)
        self.assertIn('location: "adjacent"', javascript)
        self.assertIn('presentation-export-warnings', javascript)
        self.assertIn('function showPresentationExportResult(result)', javascript)
        self.assertIn('function openPresentationStyleDialog()', javascript)
        self.assertIn('function exportSelectedPresentationStyle()', javascript)

    def test_markdown_backup_roles_feed_the_same_live_presentation_model(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('WORKBENCH_MARKDOWN_ROLE_RE', javascript)
        self.assertIn('function parsePresentationMarkdownBlock(source, index)', javascript)
        self.assertIn('if (parsed.role === "skip") return;', javascript)
        self.assertIn('parsed.role === "subslide"', javascript)
        self.assertIn('markdownPresentationItem(parsed.source, parsed.sourceIndex, parsed.role)', javascript)
        self.assertIn('currentPresentationSlide(model).items.push', javascript)

    def test_ordinary_markdown_remains_document_first_while_slides_md_is_presentation_first(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('isPresentationMarkdownPath(currentFile)', javascript)
        self.assertIn('openFile(item.path, { purposeOverride: "documents" })', javascript)
        self.assertIn('openFile(item.path, { purposeOverride: "presentations" })', javascript)

    def test_export_ui_is_preflighted_and_non_executing(self):
        javascript = JAVASCRIPT.read_text(encoding="utf-8")
        self.assertIn('Loading renderer capabilities and saved presentation settings', javascript)
        self.assertIn('capabilities.outputs', javascript)
        self.assertIn('api(presentationStyleUrl(session, "/exports"))', javascript)
        self.assertIn('function presentationStyleRequestBody(', javascript)
        self.assertIn('function showPresentationExportResult(result)', javascript)
        css = STYLES.read_text(encoding="utf-8")
        self.assertIn('.notebook-presentation', css)
        self.assertIn('.presentation-style-dialog', css)


if __name__ == "__main__":
    unittest.main()
