from __future__ import annotations

from dataclasses import dataclass, field
import html
import re
from typing import Any


_NODE_RE = re.compile(r"^(.*?)(?:\s+\[([A-Za-z][A-Za-z0-9_-]*)\])?\s*$")
_DIRECTIVE_RE = re.compile(r"^@(direction|preset)\s+(.+?)\s*$", re.IGNORECASE)
VALID_DIRECTIONS = {"TB", "TD", "BT", "LR", "RL"}
VALID_PRESETS = {"minimal", "architecture", "research", "pipeline"}


class DiagramSyntaxError(ValueError):
    """Raised when a .diagram source file cannot be parsed safely."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class DiagramNode:
    label: str
    kind: str = "default"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "kind": self.kind, "note": self.note}


@dataclass(frozen=True)
class DiagramEdge:
    source: str
    target: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target}


@dataclass
class DiagramDocument:
    nodes: dict[str, DiagramNode] = field(default_factory=dict)
    edges: list[DiagramEdge] = field(default_factory=list)
    direction: str = "TB"
    preset: str = "architecture"

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
            "direction": self.direction,
            "preset": self.preset,
        }


def _parse_node_spec(text: str, line_number: int) -> tuple[str, str]:
    match = _NODE_RE.fullmatch(text.strip())
    if not match:
        raise DiagramSyntaxError([f"Line {line_number}: invalid node declaration."])

    label = match.group(1).strip()
    kind = (match.group(2) or "default").strip().lower()
    if not label:
        raise DiagramSyntaxError([f"Line {line_number}: node label cannot be empty."])
    if "->" in label or label.startswith("::"):
        raise DiagramSyntaxError([f"Line {line_number}: invalid node label {label!r}."])
    return label, kind


def _merge_node(
    document: DiagramDocument,
    label: str,
    kind: str,
    line_number: int,
    errors: list[str],
) -> None:
    existing = document.nodes.get(label)
    if existing is None:
        document.nodes[label] = DiagramNode(label=label, kind=kind)
        return

    if existing.kind == "default" and kind != "default":
        existing.kind = kind
    elif kind != "default" and existing.kind != kind:
        errors.append(
            f"Line {line_number}: node {label!r} was already declared as "
            f"[{existing.kind}], not [{kind}]."
        )


def _apply_directive(
    document: DiagramDocument,
    name: str,
    value: str,
    line_number: int,
    errors: list[str],
) -> None:
    name = name.lower()
    value = value.strip()
    if name == "direction":
        direction = value.upper()
        if direction not in VALID_DIRECTIONS:
            errors.append(
                f"Line {line_number}: unsupported direction {value!r}; "
                f"use one of {', '.join(sorted(VALID_DIRECTIONS))}."
            )
            return
        document.direction = direction
    elif name == "preset":
        preset = value.lower()
        if preset not in VALID_PRESETS:
            errors.append(
                f"Line {line_number}: unsupported preset {value!r}; "
                f"use one of {', '.join(sorted(VALID_PRESETS))}."
            )
            return
        document.preset = preset


def parse_diagram(source: str) -> DiagramDocument:
    """Parse the small, line-oriented .diagram format into a graph document.

    Supported forms::

        @direction TB
        @preset architecture

        Source [service]
          -> Target [database]
          :: optional note attached to Source

        Other Source -> Other Target [hardware]

    Blank lines and lines whose first non-space characters are ``//`` are ignored.
    Labels are document-local identifiers: repeating a label refers to the same node.
    """

    document = DiagramDocument()
    errors: list[str] = []
    current_label: str | None = None
    seen_edges: set[tuple[str, str]] = set()

    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        directive = _DIRECTIVE_RE.fullmatch(stripped)
        if directive:
            _apply_directive(
                document,
                directive.group(1),
                directive.group(2),
                line_number,
                errors,
            )
            continue
        if stripped.startswith("@"):
            errors.append(
                f"Line {line_number}: unknown diagram directive. "
                "Supported directives are @direction and @preset."
            )
            continue

        try:
            if stripped.startswith("::"):
                if current_label is None:
                    errors.append(
                        f"Line {line_number}: '::' requires a node declaration before it."
                    )
                    continue
                note = stripped[2:].strip()
                if not note:
                    errors.append(f"Line {line_number}: node note cannot be empty.")
                    continue
                node = document.nodes[current_label]
                node.note = f"{node.note}\n{note}".strip() if node.note else note
                continue

            if stripped.startswith("->"):
                if current_label is None:
                    errors.append(
                        f"Line {line_number}: '->' requires a source node before it."
                    )
                    continue
                target_text = stripped[2:].strip()
                target_label, target_kind = _parse_node_spec(target_text, line_number)
                _merge_node(document, target_label, target_kind, line_number, errors)
                edge_key = (current_label, target_label)
                if edge_key not in seen_edges:
                    document.edges.append(DiagramEdge(*edge_key))
                    seen_edges.add(edge_key)
                continue

            if "->" in stripped:
                source_text, target_text = stripped.split("->", 1)
                source_label, source_kind = _parse_node_spec(source_text, line_number)
                target_label, target_kind = _parse_node_spec(target_text, line_number)
                _merge_node(document, source_label, source_kind, line_number, errors)
                _merge_node(document, target_label, target_kind, line_number, errors)
                edge_key = (source_label, target_label)
                if edge_key not in seen_edges:
                    document.edges.append(DiagramEdge(*edge_key))
                    seen_edges.add(edge_key)
                current_label = source_label
                continue

            label, kind = _parse_node_spec(stripped, line_number)
            _merge_node(document, label, kind, line_number, errors)
            current_label = label
        except DiagramSyntaxError as exc:
            errors.extend(exc.errors)

    if not document.nodes and not errors:
        errors.append("Diagram is empty. Add at least one node.")

    if errors:
        raise DiagramSyntaxError(errors)
    return document


def serialize_diagram(document: DiagramDocument) -> str:
    """Serialize a graph into the canonical, human-editable .diagram form."""

    outgoing: dict[str, list[str]] = {label: [] for label in document.nodes}
    for edge in document.edges:
        outgoing.setdefault(edge.source, []).append(edge.target)

    blocks: list[str] = [
        f"@direction {document.direction}",
        f"@preset {document.preset}",
    ]
    for label, node in document.nodes.items():
        kind_suffix = f" [{node.kind}]" if node.kind != "default" else ""
        lines = [f"{label}{kind_suffix}"]
        if node.note:
            lines.extend(f"  :: {note}" for note in node.note.splitlines() if note.strip())
        for target in outgoing.get(label, []):
            target_node = document.nodes[target]
            target_kind = (
                f" [{target_node.kind}]" if target_node.kind != "default" else ""
            )
            lines.append(f"  -> {target}{target_kind}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks).rstrip() + "\n"


def _node_shape(node_id: str, display: str, kind: str) -> str:
    """Return Mermaid node syntax with a useful shape for known semantic kinds."""
    if kind == "database":
        return f'{node_id}[("{display}")]'
    if kind == "interface":
        return f'{node_id}(["{display}"])'
    if kind == "hardware":
        return f'{node_id}[["{display}"]]'
    if kind == "custom":
        return f'{node_id}{{{{"{display}"}}}}'
    return f'{node_id}["{display}"]'


def _preset_styles(preset: str) -> list[str]:
    """Mermaid class definitions for deterministic presentation presets."""
    if preset == "minimal":
        return [
            "  classDef default fill:#ffffff,stroke:#64748b,color:#0f172a,stroke-width:1.5px;",
            "  classDef interface fill:#ffffff,stroke:#475569,color:#0f172a,stroke-width:1.5px;",
            "  classDef service fill:#ffffff,stroke:#475569,color:#0f172a,stroke-width:1.5px;",
            "  classDef database fill:#ffffff,stroke:#475569,color:#0f172a,stroke-width:1.5px;",
            "  classDef hardware fill:#ffffff,stroke:#475569,color:#0f172a,stroke-width:1.5px;",
            "  classDef custom fill:#ffffff,stroke:#475569,color:#0f172a,stroke-width:1.5px;",
            "  linkStyle default stroke:#64748b,stroke-width:1.5px;",
        ]
    if preset == "research":
        return [
            "  classDef default fill:#f8fafc,stroke:#475569,color:#172033,stroke-width:1.5px;",
            "  classDef interface fill:#eaf2ff,stroke:#466a9f,color:#17345f,stroke-width:2px;",
            "  classDef service fill:#eef2ff,stroke:#5b67a5,color:#272f67,stroke-width:1.8px;",
            "  classDef database fill:#f5efff,stroke:#7657a8,color:#3d2868,stroke-width:1.8px;",
            "  classDef hardware fill:#f1f5f9,stroke:#64748b,color:#263445,stroke-width:1.8px;",
            "  classDef custom fill:#edf8f4,stroke:#4b8574,color:#245346,stroke-width:1.8px;",
            "  linkStyle default stroke:#64748b,stroke-width:1.6px;",
        ]
    if preset == "pipeline":
        return [
            "  classDef default fill:#fff7ed,stroke:#ea580c,color:#7c2d12,stroke-width:1.8px;",
            "  classDef interface fill:#ffedd5,stroke:#c2410c,color:#7c2d12,stroke-width:2px;",
            "  classDef service fill:#fff7ed,stroke:#ea580c,color:#7c2d12,stroke-width:1.8px;",
            "  classDef database fill:#fef3c7,stroke:#d97706,color:#78350f,stroke-width:1.8px;",
            "  classDef hardware fill:#f3f4f6,stroke:#6b7280,color:#1f2937,stroke-width:1.8px;",
            "  classDef custom fill:#ecfdf5,stroke:#059669,color:#065f46,stroke-width:1.8px;",
            "  linkStyle default stroke:#ea580c,stroke-width:1.8px;",
        ]
    # architecture
    return [
        "  classDef default fill:#f8fafc,stroke:#64748b,color:#172033,stroke-width:1.5px;",
        "  classDef interface fill:#e8f3ff,stroke:#2f6fab,color:#153d66,stroke-width:2px;",
        "  classDef service fill:#e8fbf8,stroke:#238a7a,color:#155b51,stroke-width:1.8px;",
        "  classDef database fill:#f3ecff,stroke:#7c55a5,color:#442567,stroke-width:1.8px;",
        "  classDef hardware fill:#fff1df,stroke:#c76b18,color:#743b0b,stroke-width:1.8px;",
        "  classDef custom fill:#edf9e8,stroke:#579044,color:#315c24,stroke-width:1.8px;",
        "  linkStyle default stroke:#60758a,stroke-width:1.7px;",
    ]


def diagram_to_mermaid(
    document: DiagramDocument,
    direction: str | None = None,
    preset: str | None = None,
) -> str:
    """Create styled Mermaid source from a parsed diagram.

    ``direction`` and ``preset`` may temporarily override the values stored in the
    document. The builder uses those overrides for live preview before the user
    chooses to apply the settings to the source file.
    """

    direction = (direction or document.direction or "TB").upper()
    if direction not in VALID_DIRECTIONS:
        direction = "TB"
    preset = (preset or document.preset or "architecture").lower()
    if preset not in VALID_PRESETS:
        preset = "architecture"

    node_ids = {label: f"n{index}" for index, label in enumerate(document.nodes, 1)}
    lines = [f"flowchart {direction}"]

    for label, node in document.nodes.items():
        node_id = node_ids[label]
        display = html.escape(label, quote=True)
        if node.note:
            note = "<br/>".join(html.escape(part, quote=True) for part in node.note.splitlines())
            display = f"{display}<br/>{note}"
        lines.append(f"  {_node_shape(node_id, display, node.kind)}")

    for edge in document.edges:
        lines.append(f"  {node_ids[edge.source]} --> {node_ids[edge.target]}")

    known_kinds = {"interface", "service", "database", "hardware", "custom"}
    for label, node in document.nodes.items():
        class_name = node.kind if node.kind in known_kinds else "default"
        lines.append(f"  class {node_ids[label]} {class_name};")

    lines.extend(_preset_styles(preset))
    return "\n".join(lines) + "\n"
