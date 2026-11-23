"""Shared presentation contracts and local export adapters."""

from .models import (
    PresentationError,
    PresentationExportRequest,
    PresentationExportResult,
    RendererCapabilities,
    StyleReference,
)
from .renderers import PLANNED_RENDERERS, PresentationRenderer
from .native_beamer import is_beamer_entrypoint, is_beamer_source, discover_beamer_entrypoints
from .legacy_adapters import ExistingExportRenderer, existing_export_renderers
from .service import PresentationService
from .previews import PresentationPreviewService, PreviewStatus, BeamerPreviewProvider
from .profiles import PresentationBuildProfile, PresentationProfileStore, style_manifest_digest
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
    "PresentationPreviewService",
    "PreviewStatus",
    "BeamerPreviewProvider",
    "RendererCapabilities",
    "StyleReference",
    "PresentationBuildProfile",
    "PresentationProfileStore",
    "style_manifest_digest",
    "InstalledStyle",
    "PresentationStyleRegistry",
    "StyleAsset",
    "StyleManifest",
    "is_beamer_entrypoint",
    "is_beamer_source",
    "discover_beamer_entrypoints",
    "BeamerInspection",
    "BeamerThemeCandidate",
    "inspect_beamer_source",
    "import_beamer_style",
]
