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

## PS-05 — Render with a pinned imported Beamer style

The shared export service accepts an optional `StyleReference(identifier, version,
"beamer")` on a `PresentationExportRequest`, or as the `style=` keyword to
`DocumentEngine.export_presentation()`. The presentation HTTP export endpoint
accepts the same optional reference as a JSON object:

```json
{
  "renderer": "beamer",
  "format": "pdf",
  "style": {"identifier": "beamer.msu", "version": "1.0.0", "kind": "beamer"}
}
```

Style selection is **per export**; project-level persistence and the visual
style selector are deferred to PS-06/PS-07. The selected style must be installed
in the local PS-03 registry with an import-generated `beamertheme*.sty`
entrypoint, and it must allow the `beamer` renderer. The service verifies the
exact style reference and every asset digest before exporting.

`tech_documents.presentations.beamer_rendering.stage_beamer_style()` copies
verified theme assets into an automatically cleaned temporary directory and
provides recursive `TEXINPUTS` to Quarto's LaTeX toolchain. The selected Beamer
theme name is passed as a Quarto command-line metadata override (`-M theme:<name>`). Source `.md`/`.ipynb` files are not rewritten, and the
existing unstyled export routes remain unchanged. Styled Markdown writes to
`builds/presentations/`; styled notebooks write to `builds/notebooks/`.
Each styled export builds its PDF in a unique temporary output directory and
then moves the successful PDF into place, avoiding stale-output false positives.
Both send `--no-execute` so notebook code is not run during a styled export.
Styles for Reveal.js and PowerPoint are still unsupported in this sprint.

**Prerequisites:** Quarto and a locally installed TeX/LaTeX engine with any
packages required by the imported style. The registry does not install TeX
packages or invoke imported Makefiles. Importing a Beamer style is not
security verification of its LaTeX: *only compile themes you trust*. Temporary
asset staging is not an OS-level sandbox; TeX and Quarto may read project and
local files, including through existing project configuration. No cloud
compilation is used.

Validation uses simulated Quarto subprocess calls for API and renderer contracts;
Quarto is not installed in the sprint's test environment. Separately, the
original `csci447.zip` theme was imported and compiled successfully with
`pdflatex -no-shell-escape` using a newly written two-slide deck and the staged
assets. This is a TeX integration check, not a complete Quarto integration test.

## PS-06 — Per-presentation persistent build profiles

`tech_documents.presentations.profiles` persists an explicit build profile for
**each source file within its canonical project root**. Profile files are saved
outside source projects under `.workbench-presentation-configs/profiles/` at the
Workbench host base directory (ignored by Git). The profile filename is a
SHA-256 identity of the canonical project root and relative presentation source;
profiles for different projects or presentations cannot share an identifier.
Linked projects are therefore supported without modifying their repositories.
Profiles are loaded from disk on every operation, rather than cached in the
`DocumentEngine` instance.

Profile schema 1 records the renderer ID, output format, optional output basename,
optional exact `StyleReference` (kind/identifier/version), and the SHA-256 digest
of the installed **style manifest** (which contains hashes for all its assets).
A saved reference never floats to a newly installed style version. Saving and
reading verify style compatibility and installed asset integrity. A missing,
corrupted, or changed pinned style yields an explicit error instead of falling
back to a default style. Unknown profile schema versions are rejected. Profiles
are written atomically via same-directory temporary files; storage rejects
symlinks in profile paths. Files and folders are local and private to the host.

`DocumentEngine` exposes:

- `save_presentation_profile(project, filename, renderer_id=..., output_format=...,
  output_name=None, style=None)` — validate and save for only that source.
- `presentation_profile(project, filename)` — read and verify, or `None` if absent.
- `delete_presentation_profile(project, filename)` — remove one profile.
- `export_presentation(project, filename, use_saved_profile=True)` — explicitly
  use the stored renderer, format, output basename, and pinned style.

The API exposes `GET`, `PUT`, and `DELETE` on
`/api/presentations/<project>/<path:filename>/profile`. PUT accepts the
renderer/format keys used by the export API and optional `output_name` and
pinned `style` fields. A presentation export POST can now use:

```json
{"use_saved_profile": true}
```

This opt-in is deliberate: existing direct exports remain independent from
saved profiles, and a saved-profile export cannot simultaneously supply a
renderer, format, or style override. A filename-only `output_name` override is
allowed on that single export without mutating the stored profile. Custom
renderer options remain unsupported by existing PS-05 adapters, so schema 1
rejects nonempty `options` instead of saving settings which a build would ignore.
The PS-07 UI will expose profile editing and selection. Existing presentation
output names/directories are unchanged; same-named sources in one project may
still need distinct output names to prevent export file collisions.

No network or external service is involved. This metadata persistence does not
change the TeX trust model described in PS-05.

### PS-07: presentation styling interface

The Presentations toolbar now exposes **Style & export** alongside the unchanged
legacy **Other exports** and Backup paths. The new modal lists available local
renderers and their actual runtime readiness, selects only compatible installed
style versions, and can create an export with the shared `DocumentEngine` service.
Saving or clearing a profile calls PS-06's per-source profile API; choosing a
style alone never edits the Markdown/notebook source or overwrites a saved profile.

The standalone Flask adapter exposes `/api/presentation-styles` for catalog and
uninstall, and `/api/presentation-styles/{inspect,import}` for the PS-04 importer.
Sources are either ZIPs uploaded to a **temporary local directory** (discarded
after the request) or paths restricted to an already attached Workbench project.
The importer does not execute Makefiles or arbitrary project commands. The UI
requires an explicit theme candidate and version when installing; uninstall is
version-specific and warns about already-pinned profiles. Installed assets are
copied into the PS-03 registry. No external theme catalog or network compiler
is used. This UI does not provide a rendered theme gallery (reserved for PS-09).

### PS-08: Unified presentation output catalog and workflow

The Presentations wing exposes one **Style & export…** dialog for Markdown and
notebook sources. Its format picker is populated from
`DocumentEngine.presentation_export_capabilities(project, filename)["outputs"]`,
which reports **source-specific** availability and groups outputs by operation:

- `render`: Beamer PDF, Reveal.js HTML, and PowerPoint PPTX through the existing
  shared `PresentationService`, with compatible style selection and saved profiles.
- `conversion`: `.slides.md` ↔ `.ipynb` presentation transfers with slide roles
  and static notebook outputs preserved where supported. Conversions do not
  select or modify themes or renderer profiles.
- `document`: for notebook sources only, legacy notebook document exports
  (HTML, Markdown, Word, ordinary PDF). These remain distinct from styled decks.

All three operations use `POST /api/presentations/<project>/<filename>/exports`
with **exactly one** of `{renderer, format}`, `conversion_target`, or
`document_format`; only renderer exports may use a style or saved profile.
Response metadata includes `export_kind`, relative `path`, `format`, and
`download_url` at the HTTP layer. Conversions also return slide-role warnings in
`details.warnings`, shown by the unified dialog. Named conversions write into
`builds/presentations/` and cannot follow symlinked output paths outside the
project. Notebook document exports remain in `builds/notebooks/`.

`Backup` remains a separate explicit action for an *adjacent*, non-overwriting
presentation-source backup. Pre-existing `/convert` and `/api/notebooks/.../exports`
HTTP routes are retained for older clients; they no longer require a separate
presentation export dialog. The renderer-specific style import and profile APIs
from PS-07 are unchanged. PS-09 will add rendered theme previews.

### PS-09: On-demand local presentation theme previews

`PresentationPreviewService` is a renderer-neutral preview-provider registry. It
reads pinned styles from the PS-03 registry, verifies asset integrity, and stores
rendered preview artifacts under `.workbench-presentation-previews/` keyed by the
style reference plus its full manifest digest. Preview artifacts are independent
of source presentation files, project build outputs and PS-06 saved profiles.

The initial `BeamerPreviewProvider` compiles a fixed two-slide standalone TeX
sample using the selected registered theme and local `pdflatex`, then uses local
`pdftoppm` to produce two PNG thumbnails. Preview generation requires explicit
user action through a POST endpoint; selection and GET routes only retrieve
existing cached results, without invoking a compiler. A PDF remains available
for detailed inspection. Preview cache entries are invalidated by manifest digest
changes; missing styles cannot serve old previews.

Compiling LaTeX themes executes TeX macros. `-no-shell-escape` disables the usual
shell-escape mechanism, but TeX is **not an isolation sandbox**: preview only
trusted styles, and consider a container or OS-level sandbox for untrusted themes.
No Makefiles are run, no remote services are contacted, and no source content is
rewritten. Theme previews are representative sample slides rather than guarantees
of pixel-identical Quarto output. Additional preview providers can be registered
later for Reveal.js and PowerPoint; those formats are not yet previewable.

### PS-10: Native Beamer project editing and exports

A `.tex` file containing a literal `\documentclass[...]{beamer}` is a native
presentation *entrypoint*. PS-10 does not convert it to Markdown/notebooks or
apply a second Beamer style over the project's existing `\usetheme`, preamble,
styles, images, bibliography and split sources. The existing Workbench text
editor can edit the main `.tex`, auxiliary `.tex`, `.sty` and `.cls` files. The
Presentations wing now identifies native mains, has a **Find Beamer mains**
selector scoped to the configured Documents Root, and includes **Build Beamer
PDF** plus its unified **Style & export…** workflow.

`GET /api/presentations/<project>/native-beamer` returns detected main files.
The existing unified `GET/POST /api/presentations/<project>/<filename>/exports`
endpoint exposes only `beamer:pdf` for a native main; it requires `latexmk` or
Tectonic but **not Quarto**. Source fragments and non-Beamer `.tex` files cannot
be exported as presentations. Native export settings may be saved using the
same PS-06 profile store (renderer `beamer`, format `pdf`, no extra style).

The Beamer adapter calls the Workbench's existing LaTeX compilation service,
using its preflight, diagnostics, isolated source snapshot, compiler selection
and build cache. For native builds the snapshot is given recursive `TEXINPUTS`
so nested local `beamertheme*.sty` resources can be resolved without modifying
project sources or requiring a global TeX install of the theme. `latexmk` is
invoked with `-no-shell-escape`; the Tectonic fallback uses `--only-cached` to
prevent network package fetching. A completed PDF is copied atomically to the
project's `builds/presentations/` directory. Failed compilations do not publish
a new result or rewrite the original source.

This is a workflow convenience, **not a security sandbox**. TeX macros can still
read local files; use only trusted third-party Beamer projects, or run the
Workbench in an OS-level sandbox. Importing native projects is done through
existing Workbench project/folder attachment, not the PS-04 theme-only importer.
There is no Makefile execution or remote rendering service in this path.

### PS-11: Reveal.js CSS and PowerPoint reference styling

The existing `PresentationStyleRegistry` now holds two additional immutable
style kinds: `reveal` (a CSS stylesheet with optional local image/font assets)
and `powerpoint` (a `.pptx` reference document). Both are version-pinned by
manifest/asset hashes, use the same style picker and saved-profile model, and
are imported through the same local style inspection/install endpoints with
`kind: "reveal"` or `kind: "powerpoint"`. Existing Beamer import requests that
omit `kind` still default to `beamer`. CSS and PPTX may be imported as local
files, directories or ZIPs; multiple discovered candidates require explicit
selection. Imported CSS disallows `@import`, external URLs and references to
unpackaged assets. PPTX reference documents must be real Office packages
with a slide master and no external relationship targets. Import never runs
file content, templates, Makefiles, or any remote service.

The existing Quarto-backed Reveal.js and PowerPoint adapters now support an
installed style during Markdown **and notebook** export, by writing a transient
renderer-specific metadata file (`revealjs.css` or `pptx.reference-doc`) and
staging registered assets in a temporary local directory. Styled Reveal.js
exports request `embed-resources: true` to avoid dangling temporary CSS
or JavaScript paths in the published HTML. Quarto is invoked
with `--no-execute` and output is published only after a successful render.
Unstyled notebook/Markdown exports remain on their original code paths.
The style UI filters by actual renderer-compatible style kinds, and the same
profile store preserves exact style versions. There is no automatic Beamer →
CSS/PPTX translation. PS-09's preview provider still handles Beamer only;
CSS/PPTX preview providers are not included in PS-11.

Verify the Quarto CLI behavior and relative CSS asset packaging against the
installed Quarto version in the user's local environment; CI uses simulated
local Quarto calls because the validation runtime lacks Quarto.
