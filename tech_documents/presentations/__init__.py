"""Shared presentation architecture; export adapters arrive in later sprints."""

from .models import (
    PresentationError,
    PresentationExportRequest,
    PresentationExportResult,
    RendererCapabilities,
    StyleReference,
)
from .renderers import PLANNED_RENDERERS, PresentationRenderer
from .service import PresentationService

__all__ = [
    "PLANNED_RENDERERS",
    "PresentationError",
    "PresentationExportRequest",
    "PresentationExportResult",
    "PresentationRenderer",
    "PresentationService",
    "RendererCapabilities",
    "StyleReference",
]
