from __future__ import annotations

import base64
from pathlib import Path
import re
from typing import Any

from .errors import DocumentEngineError

ROLE_RE = re.compile(r"^\s*<!--\s*workbench-slide-role:\s*(slide|subslide|fragment|skip|notes)\s*-->\s*$", re.I)


def split_presentation_markdown(source: str) -> list[str]:
    """Split standalone presentation Markdown on --- outside fenced code blocks."""
    text = str(source or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, min(len(lines), 80)):
            if lines[i].strip() == "---":
                lines = lines[i + 1 :]
                break
    slides: list[list[str]] = [[]]
    fence: str | None = None
    for line in lines:
        stripped = line.lstrip()
        marker = "```" if stripped.startswith("```") else "~~~" if stripped.startswith("~~~") else None
        if marker:
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
        if fence is None and line.strip() == "---":
            slides.append([])
        else:
            slides[-1].append(line)
    return ["\n".join(part).strip("\n") for part in slides if "\n".join(part).strip()]


def _cell_role(cell: Any) -> str:
    metadata = getattr(cell, "metadata", {}) or {}
    role = ((metadata.get("slideshow") or {}).get("slide_type") or "").strip()
    if role in {"slide", "subslide", "fragment", "skip", "notes"}:
        return role
    return "slide" if getattr(cell, "cell_type", "") == "markdown" else "fragment"


def notebook_to_presentation_markdown(notebook_path: Path, destination: Path) -> dict[str, Any]:
    try:
        import nbformat
    except ImportError as exc:
        raise DocumentEngineError("Presentation conversion requires nbformat.") from exc
    notebook = nbformat.read(notebook_path, as_version=4)
    blocks: list[str] = []
    static_outputs = 0
    nonportable = 0
    for cell in notebook.cells:
        role = _cell_role(cell)
        if role == "skip":
            continue
        marker = f"<!-- workbench-slide-role: {role} -->"
        if cell.cell_type == "markdown":
            body = str(cell.source or "").strip()
        elif cell.cell_type == "code":
            body = "```python\n" + str(cell.source or "").rstrip() + "\n```"
            rendered: list[str] = []
            for output in cell.get("outputs", []):
                data = output.get("data", {}) if isinstance(output, dict) else {}
                if "image/png" in data:
                    payload = str(data["image/png"]).replace("\n", "")
                    rendered.append(f"![Notebook output](data:image/png;base64,{payload})")
                    static_outputs += 1
                elif "image/jpeg" in data:
                    payload = str(data["image/jpeg"]).replace("\n", "")
                    rendered.append(f"![Notebook output](data:image/jpeg;base64,{payload})")
                    static_outputs += 1
                else:
                    text = ""
                    if isinstance(output, dict):
                        if output.get("output_type") == "stream":
                            text = str(output.get("text", ""))
                        elif "text/plain" in data:
                            text = str(data.get("text/plain", ""))
                        elif output.get("output_type") == "error":
                            text = "\n".join(output.get("traceback", [])) or f"{output.get('ename','Error')}: {output.get('evalue','')}"
                    if text.strip():
                        rendered.append("```text\n" + text.rstrip() + "\n```")
                        static_outputs += 1
                    elif output:
                        nonportable += 1
            if rendered:
                body += "\n\n" + "\n\n".join(rendered)
        else:
            body = str(cell.source or "").strip()
        blocks.append(f"{marker}\n\n{body}".rstrip())

    front = "---\npresentation: true\nformat: workbench-slides\n---\n\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(front + "\n\n---\n\n".join(blocks) + "\n", encoding="utf-8")
    warnings: list[str] = []
    if static_outputs:
        warnings.append(f"{static_outputs} stored notebook output(s) were preserved as static Markdown fallbacks.")
    if nonportable:
        warnings.append(f"{nonportable} notebook output(s) could not be represented in portable Markdown and were omitted.")
    return {
        "static_outputs": static_outputs,
        "nonportable_outputs": nonportable,
        "slides": len(blocks),
        "warnings": warnings,
    }


def presentation_markdown_to_notebook(markdown_path: Path, destination: Path) -> dict[str, Any]:
    try:
        import nbformat
    except ImportError as exc:
        raise DocumentEngineError("Presentation conversion requires nbformat.") from exc
    source = markdown_path.read_text(encoding="utf-8")
    cells = []
    for block in split_presentation_markdown(source):
        lines = block.splitlines()
        role = "slide"
        if lines and ROLE_RE.match(lines[0]):
            role = ROLE_RE.match(lines[0]).group(1).lower()  # type: ignore[union-attr]
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines.pop(0)
        cell = nbformat.v4.new_markdown_cell("\n".join(lines).rstrip())
        cell.metadata["slideshow"] = {"slide_type": role}
        cells.append(cell)
    notebook = nbformat.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
        "workbench": {"converted_from": markdown_path.name, "presentation_backup": True},
    })
    destination.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, destination)
    return {
        "slides": len(cells),
        "static_only": True,
        "warnings": [
            "The generated notebook is a static presentation backup; Markdown conversion does not recreate executable kernel state or interactive widgets."
        ],
    }
