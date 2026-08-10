from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class FigureInsertion:
    content: str
    snippet: str
    relative_asset: str
    label: str
    warning: str = ""
    already_present: bool = False


def relative_asset_path(target_file: str, asset_file: str) -> str:
    """Return a POSIX path to *asset_file* relative to *target_file*'s directory."""
    target = PurePosixPath(target_file)
    asset = PurePosixPath(asset_file)
    base = target.parent.as_posix()
    if base == ".":
        base = ""
    return posixpath.relpath(asset.as_posix(), start=base or ".")


def default_figure_label(asset_file: str) -> str:
    stem = PurePosixPath(asset_file).stem
    token = re.sub(r"[^A-Za-z0-9:._-]+", "-", stem).strip("-._") or "diagram"
    return f"fig:{token}"


def validate_figure_label(value: str, asset_file: str) -> str:
    label = (value or "").strip() or default_figure_label(asset_file)
    if not re.fullmatch(r"[A-Za-z0-9:._-]+", label):
        raise ValueError(
            "Figure labels may contain only letters, numbers, colon, period, underscore, and hyphen."
        )
    return label


def markdown_figure_snippet(relative_asset: str, caption: str) -> str:
    alt = (caption or "Diagram").strip().replace("]", r"\]")
    return f"![{alt}]({relative_asset})"


def latex_figure_snippet(
    relative_asset: str,
    caption: str,
    label: str,
    figure_mode: str = "single",
) -> str:
    environment = "figure*" if figure_mode == "double" else "figure"
    width = r"\textwidth" if figure_mode == "double" else r"\linewidth"
    lines = [
        f"\\begin{{{environment}}}[t]",
        "    \\centering",
        f"    \\includegraphics[width={width}]{{{relative_asset}}}",
    ]
    if caption.strip():
        lines.append(f"    \\caption{{{caption.strip()}}}")
    if label:
        lines.append(f"    \\label{{{label}}}")
    lines.append(f"\\end{{{environment}}}")
    return "\n".join(lines)


def insert_figure_reference(
    content: str,
    *,
    target_file: str,
    asset_file: str,
    caption: str = "",
    label: str = "",
    figure_mode: str = "single",
    allow_duplicate: bool = False,
) -> FigureInsertion:
    """Insert a generated diagram reference into Markdown or LaTeX source.

    Markdown references are appended. LaTeX figure environments are inserted before
    the final ``\\end{document}`` when present so the document remains compilable.
    """
    target_suffix = PurePosixPath(target_file).suffix.lower()
    asset_suffix = PurePosixPath(asset_file).suffix.lower()
    relative_asset = relative_asset_path(target_file, asset_file)

    if target_suffix in {".md", ".markdown"}:
        if asset_suffix not in {".svg", ".png"}:
            raise ValueError("Markdown figure insertion supports SVG or PNG assets.")
        resolved_label = ""
        snippet = markdown_figure_snippet(relative_asset, caption)
        warning = ""
    elif target_suffix == ".tex":
        if asset_suffix not in {".pdf", ".png"}:
            raise ValueError("LaTeX figure insertion supports PDF or PNG assets.")
        if figure_mode not in {"single", "double"}:
            raise ValueError("LaTeX figure mode must be 'single' or 'double'.")
        resolved_label = validate_figure_label(label, asset_file)
        snippet = latex_figure_snippet(
            relative_asset,
            caption,
            resolved_label,
            figure_mode,
        )
        has_graphicx = bool(
            re.search(
                r"\\usepackage(?:\[[^\]]*\])?\{[^}]*\bgraphicx\b[^}]*\}",
                content,
            )
        )
        warning = "" if has_graphicx else (
            "The target LaTeX file does not appear to load graphicx; add "
            r"\usepackage{graphicx} before compiling."
        )
    else:
        raise ValueError("Figure references can only be inserted into Markdown or LaTeX files.")

    if not allow_duplicate and relative_asset in content:
        return FigureInsertion(
            content=content,
            snippet=snippet,
            relative_asset=relative_asset,
            label=resolved_label,
            warning=warning,
            already_present=True,
        )

    if target_suffix == ".tex" and "\\end{document}" in content:
        marker = content.rfind("\\end{document}")
        before = content[:marker].rstrip()
        after = content[marker:].lstrip()
        updated = f"{before}\n\n{snippet}\n\n{after}"
        if content.endswith("\n") and not updated.endswith("\n"):
            updated += "\n"
    else:
        updated = content.rstrip() + "\n\n" + snippet + "\n"

    return FigureInsertion(
        content=updated,
        snippet=snippet,
        relative_asset=relative_asset,
        label=resolved_label,
        warning=warning,
    )
