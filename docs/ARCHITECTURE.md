# Architecture

The project has two layers:

```text
Standalone Research Document Workbench
                |
                v
        tech_documents.web
                |
                v
        DocumentEngine API
                |
       +--------+---------+
       |        |         |
       v        v         v
    Projects  Diagrams  LaTeX builds
```

The reusable integration point is `tech_documents.DocumentEngine`. It contains no Flask dependency and can therefore be embedded into a separate local application.

The existing standalone browser UI is intentionally preserved under `tech_documents/web/`. The root `app.py` remains as a backward-compatible launcher; `run.py` is the preferred explicit launcher.
