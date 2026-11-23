"""Shared presentation contracts and local export adapters."""

from .models import (
    PresentationError,
    PresentationExportRequest,
    PresentationExportResult,
    RendererCapabilities,
    StyleReference,
)
from .renderers import PLANNED_RENDERERS, PresentationRenderer
from .legacy_adapters import ExistingExportRenderer, existing_export_renderers
from .service import PresentationService

__all__ = [
    "PLANNED_RENDERERS",
    "ExistingExportRenderer",
    "existing_export_renderers",
    "PresentationError",
    "PresentationExportRequest",
    "PresentationExportResult",
    "PresentationRenderer",
    "PresentationService",
    "RendererCapabilities",
    "StyleReference",
]
