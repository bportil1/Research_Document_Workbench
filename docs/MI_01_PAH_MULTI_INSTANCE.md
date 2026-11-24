# Research Document Workbench — PAH multi-instance compatibility

`tech_documents` now advertises a standard `pah.runtimes` entry point. PAH's
MI-06 instance supervisor can call `process_launch_spec(context=...)` to start
separate localhost-bound Workbench processes. The adapter does not import PAH,
access its registries, host a thread inside PAH, or replace DocumentEngine.

- `python -m tech_documents.process_ui` is a **PAH-only process entry point**.
  It requires `PAH_MODULE_INSTANCE_ID`, `PAH_MODULE_RUNTIME_DIR`, and
  `PAH_MODULE_PORT`. It uses the assigned loopback port and disables debug mode.
  Use `python run.py` for the original standalone app.
- Workbench keeps its own persistent project catalog and managed document
  directory in `$WORKBENCH_DATA_ROOT`, or if unset,
  `${XDG_DATA_HOME:-~/.local/share}/research-document-workbench`.
  This path intentionally **survives process shutdown** and is outside PAH's
  temporary module directory. The standalone app's original paths are unchanged.
- A PAH `documents` resource, when present, is offered as an *initial linked
  project*. Linking is owned by Workbench; it does not change PAH's active
  workspace and does not restrict the module's New Project controls.
- Each Workbench process uses a distinct persistent build directory under
  `<data-root>/builds/instances/<hash-of-instance-id>`. Projects, styles and
  project registry remain managed by Workbench. These build directories are
  generated outputs, not versioned source.
- Linked-project registry writes use cross-process advisory locking and atomic
  replacements. Corrupt registry JSON is reported rather than overwritten.
  Different projects in different windows are independently selectable.
- `.gitignore` excludes the repository-local registry containing machine paths,
  generated `analysis/`, `.pah/`, runtime directories and caches. Existing Git
  tracked files require an explicit `git rm --cached` (without deleting local files).

## Boundaries and outstanding limitations

The user may deliberately open the **same** document project in two processes.
Their text autosave and notebook saves are still last-writer-wins in this patch;
BroadcastChannel only synchronizes within a browser origin, so different
localhost ports do not coordinate editor ownership. Separate projects avoid this
collision; safe same-file editing requires a future source-revision/ETag save
contract and a conflict-recovery UI. Project deletion during another process's
active edit is likewise not made safe by the project catalog lock.

If an installed standalone Workbench already has a repository-local
`.workbench-projects.json` with linked projects, it is **not automatically
migrated** to the persistent PAH data directory. Attach those project folders
through Workbench's UI (or make a local backup and import the registry yourself)
so no old paths are silently overwritten or erased.

The legacy PAH embedded Workbench surface may coexist until the host migrates
its UI entry point; this adapter's legacy `launch()` intentionally does not
create an unmanaged process. Use PAH's New Instance action for independent
launches. No external network dependencies are introduced.

## Local checks

```bash
python -m pytest -q tests/test_pah_multi_instance.py tests/test_document_engine.py
python -m compileall -q tech_documents
```

From PAH's Instance Manager, launch two Workbench instances, verify different
ports/PIDs, open separate paper projects, create and compile documents in each,
and close one without changing the other. Repeat with linked projects and a
shared data directory. These live browser checks require the actual installed
PAH environment and are not covered by the repository's unit tests.
