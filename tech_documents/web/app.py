from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
)

from ..api import DocumentEngine
from ..diagrams import DiagramSyntaxError
from ..errors import DocumentEngineError
from ..paths import safe_name


engine = DocumentEngine()

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024


def _abort_engine_error(exc: DocumentEngineError) -> None:
    abort(exc.status_code, exc.message)


def _json_engine_error(exc: DocumentEngineError):
    return jsonify({"ok": False, "error": exc.message}), exc.status_code


@app.get("/")
def index() -> str:
    engine.ensure_directories()
    return render_template("index.html")


@app.get("/api/projects")
def projects() -> Response:
    return jsonify({"projects": engine.list_projects()})


@app.post("/api/projects/link")
def link_project() -> Response:
    payload = request.get_json(force=True)
    try:
        name = engine.link_project(str(payload.get("path", "")), name=str(payload.get("name", "") or "") or None)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, "project": name, "context": engine.project_context(name)})


@app.get("/api/projects/<project>/context")
def project_context(project: str) -> Response:
    try:
        return jsonify({"ok": True, **engine.project_context(project)})
    except DocumentEngineError as exc:
        return _json_engine_error(exc)


@app.put("/api/projects/<project>/context")
def update_project_context(project: str) -> Response:
    payload = request.get_json(force=True)
    try:
        result = engine.set_project_context(
            project,
            documents_root=str(payload.get("documents_root", "")),
            main_tex=str(payload.get("main_tex", "")),
        )
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, **result})


@app.post("/api/diagram/parse")
def parse_diagram_source() -> Response:
    payload = request.get_json(force=True)
    content = payload.get("content", "")
    if not isinstance(content, str):
        return jsonify({"ok": False, "errors": ["Diagram content must be text."]}), 400

    try:
        result = engine.parse_diagram(
            content,
            direction=payload.get("direction"),
            preset=payload.get("preset"),
        )
    except DiagramSyntaxError as exc:
        return jsonify({"ok": False, "errors": exc.errors}), 400
    except DocumentEngineError as exc:
        return jsonify({"ok": False, "errors": [exc.message]}), exc.status_code

    return jsonify({"ok": True, **result})


@app.post("/api/diagram/assets/<project>")
def save_diagram_asset(project: str) -> Response:
    payload = request.get_json(force=True)
    try:
        result = engine.save_diagram_asset(
            project,
            str(payload.get("path", "")),
            encoding=str(payload.get("encoding", "text")),
            content=payload.get("content", ""),
        )
    except DocumentEngineError as exc:
        _abort_engine_error(exc)

    return jsonify(
        {
            "ok": True,
            "path": result.path,
            "size": result.size,
            "download_url": f"/api/download/{safe_name(project)}/{result.path}",
        }
    )


@app.post("/api/diagram/insert/<project>")
def insert_diagram_into_document(project: str) -> Response:
    payload = request.get_json(force=True)
    try:
        result = engine.insert_diagram(
            project,
            target=str(payload.get("target", "")),
            asset=str(payload.get("asset", "")),
            caption=str(payload.get("caption", "")),
            label=str(payload.get("label", "")),
            figure_mode=str(payload.get("figure_mode", "single")),
            allow_duplicate=bool(payload.get("allow_duplicate", False)),
        )
    except DocumentEngineError as exc:
        _abort_engine_error(exc)

    return jsonify({"ok": True, **result})


@app.post("/api/projects")
def create_project() -> Response:
    payload = request.get_json(force=True)
    try:
        name = engine.create_project(str(payload.get("name", "")))
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, "project": name})


@app.delete("/api/projects/<project>")
def delete_project(project: str) -> Response:
    try:
        engine.delete_project(project)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True})


@app.get("/api/files/<project>/<path:filename>")
def read_file(project: str, filename: str) -> Response:
    try:
        result = engine.read_file(project, filename)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify(result)


@app.put("/api/files/<project>/<path:filename>")
def save_file(project: str, filename: str) -> Response:
    payload = request.get_json(force=True)
    content = payload.get("content", "")
    if not isinstance(content, str):
        abort(400, "Content must be text.")
    try:
        saved = engine.save_file(project, filename, content)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, "filename": saved})


@app.post("/api/files/<project>")
def create_file(project: str) -> Response:
    payload = request.get_json(force=True)
    requested = payload.get("path", payload.get("filename", "document.md"))
    try:
        saved = engine.create_file(
            project,
            str(requested),
            str(payload.get("content", "")),
        )
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, "filename": saved})


@app.get("/api/notebooks/capabilities")
def notebook_capabilities() -> Response:
    return jsonify(engine.notebook_capabilities())


@app.get("/api/notebooks/<project>/<path:filename>")
def read_notebook(project: str, filename: str) -> Response:
    try:
        result = engine.read_notebook(project, filename)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify(result)


@app.put("/api/notebooks/<project>/<path:filename>")
def save_notebook(project: str, filename: str) -> Response:
    payload = request.get_json(force=True)
    notebook = payload.get("notebook")
    if not isinstance(notebook, dict):
        abort(400, "Notebook data must be an object.")
    try:
        saved = engine.save_notebook(project, filename, notebook)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, "filename": saved})


@app.get("/api/notebooks/<project>/<path:filename>/kernel")
def notebook_kernel_status(project: str, filename: str) -> Response:
    try:
        result = engine.notebook_kernel_status(project, filename)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify(result)


@app.post("/api/notebooks/<project>/<path:filename>/execute")
def execute_notebook_cell(project: str, filename: str) -> Response:
    payload = request.get_json(force=True)
    source = payload.get("source", "")
    if not isinstance(source, str):
        abort(400, "Notebook cell source must be text.")
    try:
        result = engine.execute_notebook_cell(
            project,
            filename,
            source,
            timeout=float(payload.get("timeout", 120.0)),
        )
    except (TypeError, ValueError):
        abort(400, "Notebook execution timeout must be numeric.")
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify(result)


@app.post("/api/notebooks/<project>/<path:filename>/kernel/interrupt")
def interrupt_notebook_kernel(project: str, filename: str) -> Response:
    try:
        interrupted = engine.interrupt_notebook_kernel(project, filename)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, "interrupted": interrupted})


@app.post("/api/notebooks/<project>/<path:filename>/kernel/restart")
def restart_notebook_kernel(project: str, filename: str) -> Response:
    try:
        status = engine.restart_notebook_kernel(project, filename)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, "kernel": status})


@app.post("/api/notebooks/<project>/<path:filename>/kernel/shutdown")
def shutdown_notebook_kernel(project: str, filename: str) -> Response:
    try:
        stopped = engine.shutdown_notebook_kernel(project, filename)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, "stopped": stopped})


@app.get("/api/notebooks/<project>/<path:filename>/exports")
def notebook_export_capabilities(project: str, filename: str) -> Response:
    try:
        result = engine.notebook_export_capabilities(project, filename)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify(result)


@app.post("/api/notebooks/<project>/<path:filename>/exports")
def export_notebook(project: str, filename: str) -> Response:
    payload = request.get_json(force=True)
    try:
        result = engine.export_notebook(
            project,
            filename,
            format_id=str(payload.get("format", "")),
            output_name=str(payload.get("output_name", "") or "") or None,
        )
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    result["download_url"] = f"/api/download/{safe_name(project)}/{result['path']}"
    return jsonify(result)


@app.post("/api/folders/<project>")
def create_folder(project: str) -> Response:
    payload = request.get_json(force=True)
    try:
        path = engine.create_folder(project, str(payload.get("path", "")))
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, "path": path})


@app.patch("/api/items/<project>")
def move_or_rename_item(project: str) -> Response:
    payload = request.get_json(force=True)
    try:
        result = engine.move_item(
            project,
            str(payload.get("source", "")),
            str(payload.get("destination", "")),
        )
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, **result})


@app.delete("/api/items/<project>/<path:item_path>")
def delete_item(project: str, item_path: str) -> Response:
    try:
        deleted = engine.delete_item(project, item_path)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, "path": deleted})


# Backward-compatible single-file delete route.
@app.delete("/api/files/<project>/<path:filename>")
def delete_file(project: str, filename: str) -> Response:
    try:
        engine.delete_file(project, filename)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True})


@app.post("/api/upload/<project>")
def upload_file(project: str) -> Response:
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        abort(400, "No file uploaded.")

    try:
        filename = engine.upload_file(
            project,
            uploaded.filename,
            uploaded.stream,
            request.form.get("folder", ""),
        )
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return jsonify({"ok": True, "filename": filename})


@app.get("/api/project-asset/<project>/<path:filename>")
def project_asset(project: str, filename: str):
    """Serve a project asset inline for Markdown preview and local references."""
    try:
        file_path = engine.asset_path(project, filename)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return send_file(file_path, as_attachment=False)


@app.get("/api/download/<project>/<path:filename>")
def download_file(project: str, filename: str):
    try:
        file_path = engine.asset_path(project, filename)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return send_file(file_path, as_attachment=True, download_name=file_path.name)


@app.get("/api/download-project/<project>")
def download_project(project: str):
    try:
        archive_path = engine.archive_project(project)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return send_file(
        archive_path,
        as_attachment=True,
        download_name=archive_path.name,
    )


@app.post("/api/latex/projects/<project>")
def create_latex_project(project: str) -> Response:
    payload = request.get_json(force=True)
    try:
        result = engine.create_latex_project(
            project,
            directory=str(payload.get("directory", "")),
            template=str(payload.get("template", "article")),
            title=str(payload.get("title", "Research Document")),
            authors=str(payload.get("authors", "")),
            create_bibliography=bool(payload.get("create_bibliography", True)),
            create_images=bool(payload.get("create_images", True)),
            set_documents_root=bool(payload.get("set_documents_root", True)),
        )
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, **result, "context": engine.project_context(project)})


@app.post("/api/latex/preflight/<project>/<path:filename>")
def latex_preflight(project: str, filename: str) -> Response:
    try:
        result = engine.latex_preflight(project, filename)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, "preflight": result})


@app.post("/api/compile/<project>/<path:filename>")
def compile_latex(project: str, filename: str) -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        result = engine.compile_latex(project, filename, force=bool(payload.get("force", False)))
    except DocumentEngineError as exc:
        _abort_engine_error(exc)

    response = {
        "ok": result.ok,
        "error": result.error,
        "log": result.log,
        "diagnostics": list(result.diagnostics),
        "preflight": result.preflight,
    }
    if not result.ok:
        return jsonify(response), result.status_code

    assert result.pdf_path is not None
    response["pdf_url"] = f"/api/builds/{result.build_id}/{result.pdf_path.name}"
    return jsonify(response)


@app.get("/api/builds/<build_id>/<filename>")
def serve_build(build_id: str, filename: str):
    try:
        file_path = engine.build_file_path(build_id, filename)
    except DocumentEngineError as exc:
        _abort_engine_error(exc)
    return send_file(file_path, mimetype="application/pdf", conditional=True)


@app.get("/api/health")
def health() -> Response:
    return jsonify({"ok": True, **engine.health()})


def run(host: str = "127.0.0.1", port: int = 5050, debug: bool = True) -> None:
    engine.ensure_directories()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run()
