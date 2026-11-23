"""Renderer-independent contracts for Workbench presentations (PS-01).

These are *not* slide ASTs: Markdown, notebook metadata/outputs and native
LaTeX have different semantics and must keep their original source intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..errors import DocumentEngineError


class PresentationError(DocumentEngineError):
    """A presentation request or renderer contract could not be satisfied."""


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field} must be a nonempty, unpadded string.")
    if not all(ch.isascii() and (ch.islower() or ch.isdigit() or ch in "_-.") for ch in value):
        raise ValueError(f"{field} must use lowercase ASCII letters, digits, '_', '-' or '.'.")
    return value


@dataclass(frozen=True)
class StyleReference:
    """Reference to a pinned style; resolution/storage come in PS-03."""

    identifier: str
    version: str
    kind: str  # 'beamer', 'reveal', 'powerpoint', or a future adapter kind

    def __post_init__(self) -> None:
        _identifier(self.identifier, "Style identifier")
        _identifier(self.kind, "Style kind")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("Style version must be specified.")


@dataclass(frozen=True)
class PresentationExportRequest:
    """Describe an export without transforming or mutating its source.

    ``source_kind``: markdown | notebook | latex (extensible by adapters).
    ``output_format``: pdf | html | pptx (extensible by adapters).
    The pair ``renderer_id`` + ``output_format`` disambiguates Beamer PDF
    from a future renderer that also produces PDF.
    """

    source_path: Path
    project_root: Path
    source_kind: str
    renderer_id: str
    output_format: str
    style: StyleReference | None = None
    output_name: str | None = None
    options: Mapping[str, str | int | float | bool | None] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_path", Path(self.source_path))
        object.__setattr__(self, "project_root", Path(self.project_root))
        for field in ("source_kind", "renderer_id", "output_format"):
            _identifier(getattr(self, field), field)
        if self.output_name is not None and (not self.output_name.strip() or self.output_name != self.output_name.strip()):
            raise ValueError("Output name must be nonempty and unpadded when supplied.")
        if self.options is not None:
            for key, value in self.options.items():
                _identifier(key, "Option key")
                if value is not None and not isinstance(value, (str, int, float, bool)):
                    raise ValueError(f"Unsupported value for option {key!r}.")


@dataclass(frozen=True)
class PresentationExportResult:
    """A completed local artifact, reported by the chosen renderer."""

    renderer_id: str
    output_format: str
    output_path: Path

    def __post_init__(self) -> None:
        _identifier(self.renderer_id, "Renderer ID")
        _identifier(self.output_format, "Output format")
        object.__setattr__(self, "output_path", Path(self.output_path))


@dataclass(frozen=True)
class RendererCapabilities:
    """Supported combinations and *actual* runtime availability.

    Descriptions for planned adapters remain unavailable until a working
    adapter is explicitly registered. This avoids falsely advertising exports.
    """

    renderer_id: str
    label: str
    source_kinds: tuple[str, ...]
    output_formats: tuple[str, ...]
    style_kinds: tuple[str, ...] = ()
    available: bool = False
    reason: str = "Renderer is not connected to the shared export service."

    def __post_init__(self) -> None:
        _identifier(self.renderer_id, "Renderer ID")
        if not self.label.strip():
            raise ValueError("Renderer label must be nonempty.")
        if not self.source_kinds or not self.output_formats:
            raise ValueError("Renderer must declare at least one source and output format.")
        for values, field in ((self.source_kinds, "Source kind"), (self.output_formats, "Output format"), (self.style_kinds, "Style kind")):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {field.lower()} in renderer capabilities.")
            for value in values:
                _identifier(value, field)
        if not self.available and not self.reason:
            raise ValueError("Unavailable renderer must supply a reason.")

    def supports(self, source_kind: str, output_format: str, style_kind: str | None = None) -> bool:
        return (source_kind in self.source_kinds
                and output_format in self.output_formats
                and (style_kind is None or style_kind in self.style_kinds))

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.renderer_id,
            "label": self.label,
            "source_kinds": list(self.source_kinds),
            "output_formats": list(self.output_formats),
            "style_kinds": list(self.style_kinds),
            "available": self.available,
            "reason": "" if self.available else self.reason,
        }
