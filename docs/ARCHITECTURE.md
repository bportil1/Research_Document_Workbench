# Architecture

Research Document Workbench separates its reusable document engine from its standalone browser interface.

```text
Standalone Research Document Workbench
                |
                v
        tech_documents.web
                |
                v
        DocumentEngine API
                |
       +--------+---------+-----------+
       |        |         |           |
       v        v         v           v
    Projects  Diagrams  LaTeX     Notebooks
                         builds       |
                                      v
                               local Python kernel
```

The reusable integration point is `tech_documents.DocumentEngine`. It contains no Flask dependency and can therefore be embedded into another local application.

## Document types

Text-oriented Markdown, LaTeX, BibTeX, text, and `.diagram` files use the existing text document surface. Jupyter `.ipynb` files use a structured notebook surface and are never routed through the plain-text editor as JSON.

Notebook persistence uses the standard notebook model and preserves notebook metadata, cell metadata, attachments, outputs, and execution counts. Notebook dependencies are loaded only when notebook functionality is used.

## Notebook execution

The notebook runtime starts a local `python3` Jupyter kernel on first execution. Each notebook path owns a persistent kernel session for the lifetime of the Workbench process unless that kernel is restarted or shut down. The kernel starts in the document project directory and uses the Python environment of the running Workbench process.

The browser sends cell source to the reusable engine and receives standard notebook outputs. The browser is responsible for rendering supported MIME representations; the engine remains independent of browser presentation.

## Notebook presentation and export

Presentation roles are stored in the standard `cell.metadata.slideshow.slide_type` field. The browser turns those roles into a local Reveal.js deck without creating a second presentation document. The live deck retains references to the same in-memory notebook cells and uses the same persistent Python kernel for explicit live execution.

Notebook export is handled by `NotebookExportService`. It consumes the saved notebook and stored outputs without executing code. HTML, Markdown, and offline Reveal.js exports use nbconvert. Optional Quarto integration adds DOCX, PPTX, PDF, and Beamer targets; PDF-oriented formats are exposed only when a TeX engine is also detected. Exported artifacts are placed under the project `builds/notebooks/` directory.

The live presentation assets are vendored into the Workbench and served locally. Export capabilities are reported before an export is attempted so unavailable toolchains fail as explicit capability checks rather than opaque subprocess errors.

## Browser interface

The standalone interface remains under `tech_documents/web/`. It selects the normal text-document surface or the notebook surface according to the opened file type. Notebook code cells use a locally vendored Ace editor, while Markdown cells alternate between source editing and rendered form.

The root `app.py` remains a backward-compatible launcher; `run.py` is the preferred launcher.
