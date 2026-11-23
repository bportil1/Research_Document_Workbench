"""Typed adapter interface and planned renderer catalog (PS-01)."""
from __future__ import annotations

from typing import Protocol

from .models import PresentationExportRequest, PresentationExportResult, RendererCapabilities


class PresentationRenderer(Protocol):
    """Implemented by locally running renderer adapters in later sprints.

    An adapter must not execute notebook cells or download remote assets;
    source-to-renderer conversion is a separate step in the shared service.
    """

    @property
    def renderer_id(self) -> str: ...

    def capabilities(self) -> RendererCapabilities: ...

    def render(self, request: PresentationExportRequest) -> PresentationExportResult: ...


# These are design targets, NOT promises of working shared-service exports.
# Existing NotebookExportService exports continue to work independently.
PLANNED_RENDERERS: tuple[RendererCapabilities, ...] = (
    RendererCapabilities(
        renderer_id="beamer", label="Beamer (LaTeX)",
        source_kinds=("markdown", "notebook", "latex"),
        output_formats=("pdf",), style_kinds=("beamer",),
        reason="Beamer has not yet been connected to the shared presentation exporter (PS-05).",
    ),
    RendererCapabilities(
        renderer_id="reveal", label="Reveal.js",
        source_kinds=("markdown", "notebook"),
        output_formats=("html",), style_kinds=("reveal",),
        reason="Reveal.js has not yet been connected to the shared presentation exporter (PS-08).",
    ),
    RendererCapabilities(
        renderer_id="powerpoint", label="PowerPoint",
        source_kinds=("markdown", "notebook"),
        output_formats=("pptx",), style_kinds=("powerpoint",),
        reason="PowerPoint has not yet been connected to the shared presentation exporter (PS-08).",
    ),
)
