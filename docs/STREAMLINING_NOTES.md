# Streamlining pass

This pass reorganized the Research Document Workbench for use as an independent module in a larger local Project Assistant while preserving the standalone application.

## Compatibility checks performed

- Existing diagram tests preserved.
- Added reusable `DocumentEngine` regression tests for project/file management, upload/archive, path safety, diagram parsing/export/insertion, and LaTeX compilation.
- Test result at packaging time: **26 passed**.
- Original `static/app.js`, `static/styles.css`, and `templates/index.html` were moved under `tech_documents/web/` without content changes.
- Original `diagram_format.py` and `diagram_assets.py` implementations were moved under `tech_documents/diagrams/` without content changes; root import shims remain.
- All 21 original Flask route method/path signatures were retained in the standalone web application.
- Existing `documents/` project files were preserved byte-for-byte.
- `import tech_documents` does not import Flask.
- `python app.py` remains supported; `python run.py` is the preferred standalone launcher.

## Public integration boundary

```python
from tech_documents import DocumentEngine
```

The future unified host should use this API and should not depend on `tech_documents.web` internals.
