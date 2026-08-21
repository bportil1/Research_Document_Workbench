# Tech Documents module contract

`tech_documents` is the reusable document/diagram engine for the local Project Assistant architecture.

## Public integration surface

Use:

```python
from tech_documents import DocumentEngine
```

The future host should integrate through `DocumentEngine` rather than importing Flask routes or internal modules.

## Responsibilities

The module owns document-specific behavior:

- local research/document project structure;
- Markdown, LaTeX, BibTeX, text, `.diagram`, and structured `.ipynb` file operations;
- safe project-relative path handling;
- `.diagram` parsing, serialization, and Mermaid generation;
- diagram asset persistence and insertion into Markdown/LaTeX;
- local Python Jupyter notebook creation, persistence, and kernel execution;
- notebook slideshow metadata, live presentation coordination, and non-executing export orchestration;
- LaTeX build workspace creation and compilation;
- project archiving;
- the existing standalone Research Document Workbench UI.

## Standalone-only interface behavior

The browser application under `tech_documents/web/` retains the existing editor UX, including:

- file tree interaction;
- autosave;
- editor undo/redo;
- browser preview rendering;
- structured notebook cell editing and common Jupyter output rendering;
- live Reveal.js notebook presentations and preflighted notebook exports;
- Diagram Builder controls;
- browser-side SVG/PNG/PDF diagram export;
- CDN-loaded browser rendering libraries.

These features remain available in the standalone app, but they are not requirements of the public Python API.

## Does not own in the future unified host

The eventual Project Assistant host should own general workspace conveniences such as:

- the general-purpose project file browser;
- lightweight Python code editing;
- integrated terminal;
- Python virtual-environment creation/selection;
- running Python source files;
- cross-module workflows involving the Code Analyzer or Reference Manager.

The standalone editor remains fully functional; this boundary only prevents the unified host from needing to embed its Flask/browser implementation.

## Dependency rule

`tech_documents` core must not depend on Flask. Flask is used only by `tech_documents.web`. Notebook dependencies are loaded lazily by the reusable notebook runtime so hosts that do not use notebooks are not forced to initialize Jupyter. Export tooling is capability-gated: nbconvert is used for local HTML/Markdown/Reveal output, while Quarto and LaTeX remain optional external tools for additional formats.

Other major modules (`code_analyzer`, `reference_manager`) should not be imported by this module. Cross-module behavior belongs in the future host's integration layer.
