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
from .beamer_importer import (
    BeamerInspection, BeamerThemeCandidate, import_beamer_style, inspect_beamer_source,
)
from .style_registry import (
    InstalledStyle,
    PresentationStyleRegistry,
    StyleAsset,
    StyleManifest,
)

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
    "InstalledStyle",
    "PresentationStyleRegistry",
    "StyleAsset",
    "StyleManifest",
    "BeamerInspection",
    "BeamerThemeCandidate",
    "inspect_beamer_source",
    "import_beamer_style",
]
