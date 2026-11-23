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

## Shared presentation service — PS-01 foundation

`tech_documents.presentations` introduces a browser-independent boundary for
future presentation rendering. `DocumentEngine.presentations` provides the
`PresentationService`, and `DocumentEngine.presentation_renderer_capabilities()`
exposes the renderer catalog. These are additive: existing notebook exports,
Markdown presentation conversion, and live Reveal.js playback are **unchanged**.

- `PresentationExportRequest` records the original source path/kind, project,
  renderer, output format, optional pinned style reference and build options.
  Sources remain in their native Markdown, `.ipynb`, or LaTeX form; no lossy
  universal slide AST is imposed.
- `RendererCapabilities` describes accepted source/output/style combinations
  and actual availability. Unimplemented Beamer, Reveal.js and PowerPoint
  shared-service adapters are intentionally reported as *unavailable* even
  when an existing legacy notebook export can produce that format.
- `PresentationRenderer` is a protocol for future local adapters and
  `PresentationService` handles registration, compatibility checks, dispatch,
  and project-local input/output containment.
- `StyleReference` identifies a pinned style and type, but does **not** resolve
  theme directories or install packages yet. That is PS-03/PS-04.

The shared service does not render anything until a functioning adapter is
registered. PS-02 will connect existing exporters to the shared entry point;
PS-03 will add a persistent style registry; PS-04/PS-05 will import and render
Beamer themes (including the `csci447` acceptance fixture). No new build
commands, third-party dependencies or network access are introduced by PS-01.

## PS-02 — Unified presentation exports (existing engines)

`DocumentEngine.export_presentation` is the common browser-independent entry
point for Markdown (`.md`, `.markdown`) and notebook (`.ipynb`) slide exports.
`DocumentEngine.presentation_export_capabilities` reports renderers that can
handle a particular source on the current machine. The shared
`PresentationService` registers three `ExistingExportRenderer` adapters:

- **Beamer PDF**: Quarto and a local LaTeX engine; notebook rendering delegates
  to `NotebookExportService` and Markdown rendering uses local Quarto directly.
- **Reveal.js HTML**: notebooks delegate to the existing offline nbconvert and
  vendored-assets export; Markdown uses Quarto `revealjs` (the HTML and local
  resources come from Quarto's renderer, not the notebook assets).
- **PowerPoint PPTX**: Quarto, using the existing notebook exporter for
  `.ipynb` and directly rendering Markdown presentations otherwise.

The shared adapters reject custom styles and arbitrary build options until
registry and style-aware rendering support are implemented in later sprints.
Markdown Quarto renders explicitly use `--no-execute` and leave source text
untouched. All output stays under the selected project. Notebook exports keep
using `builds/notebooks/`; Markdown presentation exports use
`builds/presentations/`. Non-presentation notebook exports stay on the existing
`NotebookExportService` path. Presentation formats on the existing notebook
export endpoint now dispatch through the common service but retain their
legacy response keys, format IDs and output paths.

The reusable engine exposes the above functionality without Flask. Optional
HTTP routes are:

- `GET /api/presentations/<project>/<filename>/exports`: renderer capabilities
  scoped to the requested Markdown/notebook source.
- `POST /api/presentations/<project>/<filename>/exports` with JSON
  `{ "renderer": "beamer|reveal|powerpoint", "format": "pdf|html|pptx",
  "output_name": "optional" }`: runs an available export. The server response
  includes project-relative output path and download URL.

No new graphical controls, theme import, style persistence, or native `.tex`
rendering are introduced in PS-02. Those remain separately scheduled.

## PS-03 — Persistent presentation style registry

`DocumentEngine.presentation_styles` is a local `PresentationStyleRegistry` rooted at
`<workbench base>/.workbench-presentation-styles/`, kept out of Git by default.
`DocumentEngine.presentation_style_catalog(kind=..., renderer_id=...)` lists
installed style manifests without needing an active presentation or a browser.
`PresentationService` can optionally receive the registry, validating pinned
style references before dispatching to a renderer that advertises style support.
The PS-02 export adapters **still reject custom styles** until PS-05 adds
style-aware rendering; registering a style does not imply it is renderable.

The registry stores immutable packages at
`styles/<kind>/<identifier>/<version>/`, each containing a JSON manifest and
copied `assets/`. Schema v1 records a display label, optional description and
provenance label, compatible renderer IDs, and for each asset its canonical
relative path, byte size and SHA-256. Callers reference a specific version using
`StyleReference(identifier, version, kind)`; a change must be installed as a
new version rather than overwriting the previous one.

- `install(...)` copies only a caller-provided list of local relative asset paths
  into a temporary staging directory, then atomically publishes the package.
  It rejects traversal paths, symlinks, duplicates, and oversized asset sets.
- `list_styles(...)` discovers versions and optionally filters by style kind or
  compatible renderer. A corrupt manifest is reported rather than silently
  accepted. It does not compile or execute any theme content.
- `resolve(reference, renderer_id=...)` checks the exact manifest/version,
  declared renderer compatibility, and asset integrity. `uninstall(reference)`
  removes one version without disturbing other styles or versions.
- No remote services, external asset downloads, imported Makefile execution,
  GUI controls, Beamer project parsing, or ZIP extraction are part of PS-03.
  Beamer discovery/import is PS-04; style-aware compilation is PS-05.

Runtime-independent style metadata and assets are separate from presentation
sources, which remain unchanged; no style persistence is written into project
content in this sprint. Installed styles are a local per-Workbench registry and
must be explicitly exported or reinstalled to transfer between machines.

## PS-04 — Local Beamer directory/ZIP discovery and theme import

`tech_documents.presentations.inspect_beamer_source(source)` inspects a local
folder or `.zip` **without extracting it**, executing build scripts, or invoking
LaTeX. It reports independently importable `beamertheme*.sty` candidates,
Beamer `.tex` project entrypoints, project-to-theme name associations, external
TeX package *names* (not verified installations), and possible unresolved
static dependencies. This is a best-effort static inspection: dynamic TeX macros,
files referenced outside the theme bundle and TeX distribution configuration
may still require manual attention.

`import_beamer_style(registry, source, version=..., selector=...)` installs **only
the selected theme directory's styles and supporting assets**, not the source
presentation's slide content, Makefiles, or unrelated PDFs. If more than one
theme is discovered, the exact inspection-provided `selector` is required.
Imported assets are flattened relative to the selected theme directory, so a
nested project bundle yields a self-contained style package with, for example,
`assets/beamerthemeMSU.sty` and `assets/MSUlogoV.png`. The PS-03 registry
retains its existing manifest schema, with an optional renderer-neutral
`entrypoint` field recording the primary theme file. Old PS-03 manifests without
`entrypoint` continue to load and resolve unchanged. Imported styles remain
immutable and version-pinned, with SHA-256 verification on resolution.

ZIPs are validated for traversal, absolute/Windows paths, duplicate names,
symlinks/special entries, encrypted entries, entry count/size, overall expanded
size, and suspicious compression ratios. Directories similarly reject symlinks,
nonregular files, and oversized file sets. Only theme resources are copied into
a staging directory; no source files are modified and no arbitrary Makefile is
run. Imported LaTeX is still **not trusted to execute**: compilation requires
separate runtime controls during PS-05.

`DocumentEngine.inspect_beamer_styles(path)` and
`DocumentEngine.import_beamer_style(path, version=..., selector=...)` provide
browser-independent application entry points. Neither adds an HTTP route or UI
control yet; PS-07 covers the style selector and theme management interface.
The PS-02 existing exporters continue to reject custom styles until PS-05.

Acceptance case: the `csci447.zip` project has two inspected `theory.tex`
entrypoints and one reusable MSU theme at
`csci447/theory_week/beamerthemeNISL_MSU/beamerthemeMSU.sty`, with four `.sty`
files and three logos registered. The standalone style package includes no
slide content or project Makefile. This tests import and persistence only, not
successful Beamer compilation or the future export style selection workflow.
