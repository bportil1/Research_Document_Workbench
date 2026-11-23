from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import tempfile
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
from ..presentations import StyleReference, PresentationError, BrandingTokens
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


@app.post("/api/presentations/<project>/<path:filename>/convert")
def convert_presentation(project: str, filename: str) -> Response:
    payload = request.get_json(force=True)
    try:
        result = engine.convert_presentation(
            project,
            filename,
            target=str(payload.get("target", "")),
            output_name=str(payload.get("output_name", "") or "") or None,
            location=str(payload.get("location", "build") or "build"),
        )
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    result["download_url"] = f"/api/download/{safe_name(project)}/{result['path']}"
    return jsonify(result)


@app.get("/api/presentations/<project>/native-beamer")
def native_beamer_entrypoints(project: str) -> Response:
    try:
        paths = engine.native_beamer_entrypoints(project)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, "entrypoints": paths})


@app.get("/api/presentations/<project>/<path:filename>/exports")
def presentation_export_capabilities(project: str, filename: str) -> Response:
    try:
        result = engine.presentation_export_capabilities(project, filename)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify(result)


# PS-07: Presentation styles are managed only by this local Workbench process.
# Browser-supplied filesystem paths are restricted to an attached Workbench project.
# A ZIP upload is staged in a disposable local directory and is never executed.
@contextmanager
def _presentation_style_import_source():
    archive = request.files.get("archive")
    payload = request.form if archive is not None else request.get_json(silent=True)
    if not isinstance(payload, dict) and archive is None:
        raise PresentationError("Style import requires JSON or a local file upload.")
    if archive is not None:
        kind = payload.get("kind", "beamer")
        allowed = {"beamer": {".zip"}, "reveal": {".zip", ".css"},
                   "powerpoint": {".zip", ".pptx"}}
        if kind not in allowed or Path(archive.filename or "").suffix.lower() not in allowed[kind]:
            raise PresentationError("Choose a supported ZIP, CSS, or PPTX style upload for the selected renderer.")
        with tempfile.TemporaryDirectory(prefix="workbench-style-upload-") as temporary:
            destination = Path(temporary) / ("upload" + Path(archive.filename).suffix.lower())
            archive.save(destination)
            yield destination, payload
        return
    project = payload.get("project")
    relative = payload.get("path")
    if not isinstance(project, str) or not project or not isinstance(relative, str):
        raise PresentationError("Choose a Workbench project and a relative directory or ZIP path.")
    source = engine.item_path(project, relative, allow_empty=True)
    if not source.exists():
        raise PresentationError("Selected style source does not exist in this project.")
    yield source, payload


@app.get("/api/presentation-styles")
def presentation_styles() -> Response:
    try:
        styles = engine.presentation_style_catalog()
        renderers = engine.presentation_renderer_capabilities()
    except (DocumentEngineError, ValueError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"styles": styles, "renderers": renderers})


# PS-09: separate explicit preview compilation from read-only inspection.
# Local TeX compilation of a theme may execute macros: preview only trusted
# themes and never compile as a side effect of selecting one in the browser.
def _presentation_preview_reference(kind: str, identifier: str, version: str) -> StyleReference:
    return StyleReference(identifier=identifier, version=version, kind=kind)


def _presentation_preview_urls(kind: str, identifier: str, version: str, result: dict[str, object]) -> dict[str, object]:
    if result["cached"]:
        from flask import url_for
        def asset(name: str) -> str:
            return url_for("presentation_style_preview_file", kind=kind,
                           identifier=identifier, version=version, filename=name)
        result["images"] = [asset(name) for name in result["pages"]]
        result["pdf_url"] = asset("preview.pdf")
    else:
        result["images"] = []
        result["pdf_url"] = None
    return result


@app.get("/api/presentation-styles/<kind>/<identifier>/<version>/preview")
def presentation_style_preview_status(kind: str, identifier: str, version: str) -> Response:
    try:
        ref = _presentation_preview_reference(kind, identifier, version)
        data = engine.presentation_style_preview(ref)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify(_presentation_preview_urls(kind, identifier, version, data))


@app.post("/api/presentation-styles/<kind>/<identifier>/<version>/preview")
def generate_presentation_style_preview(kind: str, identifier: str, version: str) -> Response:
    try:
        ref = _presentation_preview_reference(kind, identifier, version)
        data = engine.presentation_style_preview(ref, generate=True)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify(_presentation_preview_urls(kind, identifier, version, data))


@app.get("/api/presentation-styles/<kind>/<identifier>/<version>/preview/files/<filename>")
def presentation_style_preview_file(kind: str, identifier: str, version: str, filename: str) -> Response:
    try:
        ref = _presentation_preview_reference(kind, identifier, version)
        path = engine.presentation_style_preview_file(ref, filename)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    response = send_file(path, mimetype="application/pdf" if filename.endswith(".pdf") else "image/png")
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.post("/api/presentation-styles/inspect")
def inspect_presentation_style() -> Response:
    try:
        with _presentation_style_import_source() as (source, payload):
            kind = payload.get("kind", "beamer")
            if kind == "beamer":
                inspected = engine.inspect_beamer_styles(source)
            elif kind in {"reveal", "powerpoint"}:
                inspected = engine.inspect_asset_styles(source, kind=kind)
            else:
                raise PresentationError("Unsupported presentation style renderer.")
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"inspection": inspected})


@app.post("/api/presentation-styles/import")
def import_presentation_style() -> Response:
    try:
        with _presentation_style_import_source() as (source, payload):
            kind = payload.get("kind", "beamer")
            if kind not in {"beamer", "reveal", "powerpoint"}:
                raise PresentationError("Unsupported presentation style renderer.")
            version = payload.get("version", "")
            if not isinstance(version, str):
                raise PresentationError("Style version must be a string.")
            options = {}
            for field in ("selector", "identifier", "label", "description"):
                value = payload.get(field)
                if value is not None and not isinstance(value, str):
                    raise PresentationError(f"{field} must be a string.")
                if value is not None and (field == "description" or value):
                    options[field] = value
            if kind == "beamer":
                manifest = engine.import_beamer_style(source, version=version, **options)
            else:
                manifest = engine.import_asset_style(source, kind=kind, version=version, **options)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"ok": True, "style": manifest}), 201


# PS-12: portable, local-only style families and immutable ZIP bundles.
@app.get("/api/presentation-style-families")
def presentation_style_families() -> Response:
    try:
        families = engine.presentation_style_family_catalog()
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"families": families})


@app.post("/api/presentation-style-families")
def create_presentation_style_family() -> Response:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json_engine_error(PresentationError("Family request must be a JSON object."))
    try:
        if set(payload) != {"identifier", "version", "label", "description", "branding", "variants"}:
            raise PresentationError("Invalid style family request fields.")
        selections = payload["variants"]
        if not isinstance(selections, list) or not 1 <= len(selections) <= 16:
            raise PresentationError("Style family needs 1–16 renderer variants.")
        variants, overrides, logos = {}, {}, {}
        for item in selections:
            if not isinstance(item, dict) or set(item) != {"renderer_id", "style", "branding", "logo_asset"}:
                raise PresentationError("Invalid renderer variant selection.")
            renderer = item["renderer_id"]
            style = item["style"]
            if renderer in variants or not isinstance(style, dict) or set(style) != {"kind", "identifier", "version"}:
                raise PresentationError("Repeated renderer or invalid style reference.")
            variants[renderer] = StyleReference(**style)
            overrides[renderer] = BrandingTokens.from_dict(item["branding"])
            logos[renderer] = item["logo_asset"]
        family = engine.create_presentation_style_family(
            identifier=payload["identifier"], version=payload["version"],
            label=payload["label"], description=payload["description"],
            branding=BrandingTokens.from_dict(payload["branding"]),
            variants=variants, overrides=overrides, logos=logos,
        )
    except (DocumentEngineError, ValueError, TypeError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"ok": True, "family": family}), 201


@app.delete("/api/presentation-style-families/<identifier>/<version>")
def delete_presentation_style_family(identifier: str, version: str) -> Response:
    try:
        engine.presentation_style_families.uninstall(identifier, version)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"ok": True})


def _download_style_bundle(*, style=None, family_id=None, family_version=None):
    # A response-local tempfile is needed only while Flask reads send_file.
    # The response must include the actual archive bytes before cleanup.
    temporary = tempfile.TemporaryDirectory(prefix="workbench-export-bundle-")
    try:
        target = Path(temporary.name) / "presentation-styles.zip"
        engine.export_presentation_style_bundle(target, style=style, family_id=family_id,
                                                family_version=family_version)
        response = send_file(target, mimetype="application/zip", as_attachment=True,
                             download_name="presentation-styles.zip")
        response.headers["Cache-Control"] = "private, no-store"
        response.call_on_close(temporary.cleanup)
        return response
    except Exception:
        temporary.cleanup()
        raise


@app.get("/api/presentation-style-families/<identifier>/<version>/bundle")
def download_presentation_style_family(identifier: str, version: str) -> Response:
    try:
        return _download_style_bundle(family_id=identifier, family_version=version)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))


@app.get("/api/presentation-styles/<kind>/<identifier>/<version>/bundle")
def download_portable_presentation_style(kind: str, identifier: str, version: str) -> Response:
    try:
        return _download_style_bundle(style=StyleReference(identifier=identifier, version=version, kind=kind))
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))


@app.post("/api/presentation-style-bundles/import")
def upload_portable_presentation_styles() -> Response:
    archive = request.files.get("archive")
    if archive is None or Path(archive.filename or "").suffix.lower() != ".zip":
        return _json_engine_error(PresentationError("Choose a local portable presentation .zip package."))
    try:
        with tempfile.TemporaryDirectory(prefix="workbench-import-bundle-") as temporary:
            target = Path(temporary) / "presentation-styles.zip"
            archive.save(target)
            result = engine.import_presentation_style_bundle(target)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"ok": True, **result}), 201


@app.delete("/api/presentation-styles/<kind>/<identifier>/<version>")
def uninstall_presentation_style(kind: str, identifier: str, version: str) -> Response:
    try:
        reference = StyleReference(identifier=identifier, version=version, kind=kind)
        engine.uninstall_presentation_style(reference)
    except (DocumentEngineError, ValueError, OSError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    return jsonify({"ok": True})


@app.get("/api/presentations/<project>/<path:filename>/profile")
def get_presentation_profile(project: str, filename: str) -> Response:
    try:
        profile = engine.presentation_profile(project, filename)
    except (DocumentEngineError, ValueError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else DocumentEngineError(str(exc)))
    return jsonify({"profile": profile})


@app.put("/api/presentations/<project>/<path:filename>/profile")
def put_presentation_profile(project: str, filename: str) -> Response:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json_engine_error(PresentationError("Presentation profile request must be a JSON object."))
    if set(payload) - {"renderer", "format", "output_name", "style", "options"}:
        return _json_engine_error(PresentationError("Unsupported presentation profile fields."))
    try:
        style_data = payload.get("style")
        style = None
        if style_data is not None:
            if not isinstance(style_data, dict) or set(style_data) != {"identifier", "version", "kind"}:
                raise PresentationError("Style requires identifier, version, and kind.")
            style = StyleReference(**style_data)
        options = payload.get("options", {})
        profile = engine.save_presentation_profile(
            project, filename,
            renderer_id=payload.get("renderer", ""),
            output_format=payload.get("format", ""),
            output_name=payload.get("output_name"),
            style=style, options=options,
        )
    except (DocumentEngineError, ValueError, TypeError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else DocumentEngineError(str(exc)))
    return jsonify({"ok": True, "profile": profile})


@app.delete("/api/presentations/<project>/<path:filename>/profile")
def delete_presentation_profile(project: str, filename: str) -> Response:
    try:
        deleted = engine.delete_presentation_profile(project, filename)
    except DocumentEngineError as exc:
        return _json_engine_error(exc)
    return jsonify({"ok": True, "deleted": deleted})


@app.post("/api/presentations/<project>/<path:filename>/exports")
def export_presentation(project: str, filename: str) -> Response:
    """Unified local presentation output: render, convert, or notebook document."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json_engine_error(PresentationError("Presentation export request must be a JSON object."))
    allowed = {"renderer", "format", "output_name", "style", "use_saved_profile", "conversion_target", "document_format"}
    if set(payload) - allowed:
        return _json_engine_error(PresentationError("Unsupported presentation export fields."))
    try:
        style_data = payload.get("style")
        style = None
        if style_data is not None:
            if not isinstance(style_data, dict) or set(style_data) != {"identifier", "version", "kind"}:
                raise PresentationError("Style requires identifier, version, and kind.")
            style = StyleReference(**style_data)
        use_saved_profile = payload.get("use_saved_profile", False)
        if type(use_saved_profile) is not bool:
            raise PresentationError("use_saved_profile must be a boolean.")
        conversion_target = payload.get("conversion_target")
        document_format = payload.get("document_format")
        if conversion_target is not None and not isinstance(conversion_target, str):
            raise PresentationError("Conversion target must be a string.")
        if document_format is not None and not isinstance(document_format, str):
            raise PresentationError("Document format must be a string.")
        output_name = payload.get("output_name")
        if output_name is not None and not isinstance(output_name, str):
            raise PresentationError("Output filename must be a string.")
        result = engine.export_presentation(
            project, filename,
            renderer_id=None if "renderer" not in payload else payload["renderer"],
            output_format=None if "format" not in payload else payload["format"],
            output_name=output_name or None,
            style=style, use_saved_profile=use_saved_profile,
            conversion_target=conversion_target, document_format=document_format,
        )
    except (DocumentEngineError, ValueError, TypeError) as exc:
        return _json_engine_error(exc if isinstance(exc, DocumentEngineError) else PresentationError(str(exc)))
    result["download_url"] = f"/api/download/{safe_name(project)}/{result['path']}"
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
