"""Browser-independent presentation renderer dispatch (PS-01)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import (
    PresentationError,
    PresentationExportRequest,
    PresentationExportResult,
    RendererCapabilities,
)
from .renderers import PLANNED_RENDERERS, PresentationRenderer


class PresentationService:
    """One dispatch boundary for all future presentation exporters.

    Legacy notebook exports are intentionally untouched in PS-01. Until PS-02
    integrates their adapters, planned renderer capabilities remain unavailable.
    """

    def __init__(self, renderers: Iterable[PresentationRenderer] = ()) -> None:
        self._renderers: dict[str, PresentationRenderer] = {}
        for renderer in renderers:
            self.register(renderer)

    def register(self, renderer: PresentationRenderer) -> None:
        capability = renderer.capabilities()
        if capability.renderer_id != renderer.renderer_id:
            raise PresentationError("Renderer identifier does not match its capabilities.")
        if renderer.renderer_id in self._renderers:
            raise PresentationError(f"Renderer {renderer.renderer_id!r} is already registered.")
        self._renderers[renderer.renderer_id] = renderer

    def capabilities(self) -> list[dict[str, object]]:
        """Report built-in targets plus any registered third-party adapters."""
        catalog = {entry.renderer_id: entry for entry in PLANNED_RENDERERS}
        for identifier, renderer in self._renderers.items():
            capability = renderer.capabilities()
            if capability.renderer_id != identifier:
                raise PresentationError(f"Renderer {identifier!r} changed its identifier.")
            catalog[identifier] = capability
        return [entry.as_dict() for entry in catalog.values()]

    def compatible_renderers(
        self, *, source_kind: str, output_format: str | None = None,
        style_kind: str | None = None, available_only: bool = True,
    ) -> list[dict[str, object]]:
        """Filter descriptions without implying unimplemented renderers work."""
        return [cap for cap in self.capabilities()
                if (source_kind in cap["source_kinds"]
                    and (output_format is None or output_format in cap["output_formats"])
                    and (style_kind is None or style_kind in cap["style_kinds"])
                    and (not available_only or cap["available"]))]

    def export(self, request: PresentationExportRequest) -> PresentationExportResult:
        renderer = self._renderers.get(request.renderer_id)
        if renderer is None:
            raise PresentationError(
                f"Renderer {request.renderer_id!r} is not connected to the shared presentation exporter."
            )
        capability: RendererCapabilities = renderer.capabilities()
        if capability.renderer_id != request.renderer_id:
            raise PresentationError("Renderer identifier changed after registration.")
        if not capability.available:
            raise PresentationError(capability.reason)
        if not capability.supports(
            request.source_kind, request.output_format,
            request.style.kind if request.style else None,
        ):
            raise PresentationError("Renderer does not support the requested source, output, or style kind.")

        project_root = request.project_root.resolve()
        source_path = request.source_path.resolve()
        if not source_path.is_file():
            raise PresentationError("Presentation source file does not exist.")
        if not source_path.is_relative_to(project_root):
            raise PresentationError("Presentation source must stay inside the project directory.")
        result = renderer.render(request)
        if not isinstance(result, PresentationExportResult):
            raise PresentationError("Renderer returned an invalid export result.")
        if result.renderer_id != request.renderer_id or result.output_format != request.output_format:
            raise PresentationError("Renderer returned a mismatched export result.")
        output_path: Path = result.output_path.resolve()
        if not output_path.is_relative_to(project_root) or not output_path.is_file():
            raise PresentationError("Renderer output is missing or outside the project directory.")
        return result
