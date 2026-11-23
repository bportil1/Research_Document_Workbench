# Presentation Subsystem — Local Acceptance Checklist (PS-13)

PS-13 closes the initial PS-01–PS-13 sprint roadmap. All checks use local
resources; this is not a replacement for interactive browser acceptance on the
machine where the Workbench runs.

## Automated acceptance

From the repository root:

```bash
python -m unittest discover -s tests -q
node --check tech_documents/web/static/app.js
python scripts/validate_presentations.py --reference-zip ~/Downloads/csci447.zip --run-tests
```

The `--reference-zip` option is optional. Point it to the **trusted**, original
local `csci447.zip` archive for the real Beamer importer and PDF/PNG preview
smoke. The script stages everything in a temporary workbench and removes it
on exit. It never invokes a package installer, Makefile, external renderer or
network service. Since LaTeX macros are not sandboxed, compile only trusted
Beamer themes. Without `--run-tests`, the script runs lightweight conversion,
profile, optional theme, and locally available render smoke checks.

The script prints `PASS`, `SKIP`, or `FAIL` for its checked paths. A `PASS for
available checks` result is **not** evidence that a skipped renderer ran.
Install all required tools *locally* before relying on the corresponding
renderer, and rerun the script on the actual deployment machine.

## Workflow matrix

| Workflow | Validation | Dependencies |
| --- | --- | --- |
| Markdown → notebook conversion | Automated source-preservation smoke | Python Workbench only |
| Notebook → Markdown conversion | Existing unit/regression suite | Notebook dependencies |
| Notebook → offline Reveal.js | Existing regression suite | nbconvert, vendored Reveal.js |
| Markdown → Beamer PDF | Simulated Quarto dispatch; real Quarto when installed | Quarto + TeX |
| Markdown → Reveal.js HTML | Simulated Quarto dispatch; real Quarto when installed | Quarto |
| Markdown → PowerPoint PPTX | Simulated Quarto dispatch; real Quarto when installed | Quarto |
| Native multi-file `.tex` → PDF | Real local compilation (conditional test) | latexmk + TeX |
| `csci447.zip` inspection/import/preview | Real archive, real TeX PDF/PNG | Trusted ZIP, pdflatex, pdftoppm |
| CSS/PPTX style import, family bundle portability | Registry and ZIP round-trip tests | Local Python |
| Saved profile and version binding | Regression and acceptance tests | Local Python |
| Browser API endpoints and downloads | Flask test-client tests, conditional | Flask |
| Browser styling and export controls | Static contract and JavaScript syntax tests | Node for syntax |

## Manual browser sign-off

1. Launch the Workbench from the updated repository. Confirm that the
   Presentations wing and **Style & export…** dialog open correctly.
2. Import trusted `csci447.zip`, select the MSU Beamer theme and create its
   local title/content preview. Reopen the dialog and verify the cached preview
   remains available without recompilation.
3. Create a small `.slides.md` presentation containing a title, mathematical
   expression, bullet list and image. Export it with the MSU theme to PDF.
   Verify colors, fonts, footers, logo, and no missing images.
4. Export the same content through Reveal.js and PPTX. Verify the result opens
   in its target viewer. Reveal.js HTML must remain usable after the temporary
   build directory is removed.
5. Save a pinned profile, close and reopen the project, and export with the
   saved profile. Confirm the exact style version is used.
6. Select a different compatible theme. Confirm the presentation source and
   original theme files remain unchanged, and that an unsupported combination
   is reported clearly.
7. Open a native multi-file Beamer project with **Find Beamer mains**, edit a
   supporting `.sty` file, and build its PDF using local TeX tools.
8. Export/import a portable style family ZIP in a separate *local* Workbench
   installation. Verify exact version fingerprints and renderer variants.
9. Export two presentations named `talk.slides.md` under different subfolders
   without manually naming their outputs. Verify distinct output paths. An
   explicitly selected output name may intentionally overwrite an older export.
10. Trigger a failed Quarto render and ensure a previous successful PDF/HTML/PPTX
    is preserved. Verify no partial file is returned as success.
11. Confirm legacy notebook export and source-conversion endpoints still work.
12. Review browser console and server logs for unexpected errors or remote
    asset requests. The Workbench should not need any external service to
    process local presentation content or installed themes.

## PS-13 integration hardening

- Nested presentation sources use a short SHA-256 suffix of their **relative
  source path** when deriving default output names. Root-level source defaults
  remain backward compatible. Explicit output names still take precedence.
  Source renames/moves therefore alter the *default* output name but do not
  mutate saved profiles or installed styles.
- Unstyled Markdown Quarto exports now build in unique local scratch folders,
  and only promote a successfully rendered artifact. Reveal.js output requests
  embedded resources so staging directories can be deleted safely.
- Quarto notebook document/presentation exports request `--no-execute` and
  use the same scratch-and-promote pattern. Existing nbconvert offline exports
  and local notebook execution controls are not replaced.
- Symlinked notebook/presentation build destinations are rejected. The core
  source, installed style manifests and saved profiles are not modified during
  export.

## Unverified until deployment acceptance

The initial PS-13 validation machine may lack **Quarto** and **Flask**. In that
case simulated adapter tests and static frontend checks pass, but real
Quarto-to-PDF/HTML/PPTX and browser/API flows remain *unverified*. Do not
advertise those paths as production-validated until the corresponding local
smoke and manual checks have actually passed on the deployment machine.

PS-09 provides rendered previews for Beamer only. Reveal.js/PPTX visual theme
previews and cross-renderer automatic branding transformations remain optional
future enhancements, not promised features of this sprint.
