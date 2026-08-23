from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import re
import shutil
import subprocess
from typing import Iterable


@dataclass(frozen=True)
class LatexDiagnostic:
    severity: str
    code: str
    message: str
    file: str = ""
    line: int | None = None
    suggestion: str = ""
    detail: str = ""
    secondary: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LatexPreflightResult:
    diagnostics: tuple[LatexDiagnostic, ...] = ()

    @property
    def blockers(self) -> tuple[LatexDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "error")

    @property
    def warnings(self) -> tuple[LatexDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": len(self.blockers),
            "warnings": len(self.warnings),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


_DOCUMENT_CLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}")
_PACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}")
_BIB_RE = re.compile(r"\\bibliography\{([^}]+)\}")
_ADDBIB_RE = re.compile(r"\\addbibresource(?:\[[^\]]*\])?\{([^}]+)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_CITE_RE = re.compile(r"\\cite[a-zA-Z*]*(?:\[[^\]]*\]){0,2}\{([^}]+)\}")
_LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
_REF_RE = re.compile(r"\\(?:ref|eqref|autoref)\{([^}]+)\}")
_BIB_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,", re.IGNORECASE)
_BIB_BLOCK_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n\s*@\w+\s*\{|\Z)", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"\btitle\s*=\s*\{\s*([^}]*)\}", re.IGNORECASE | re.DOTALL)


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _line_for(text: str, needle: str) -> int | None:
    index = text.find(needle)
    if index < 0:
        return None
    return text.count("\n", 0, index) + 1


def _kpsewhich(name: str) -> bool:
    executable = shutil.which("kpsewhich")
    if not executable:
        return True
    result = subprocess.run(
        [executable, name],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _candidate_with_suffix(base: Path, raw: str, suffix: str) -> Path:
    path = base / raw
    return path if path.suffix else path.with_suffix(suffix)


def _find_graphic(base: Path, raw: str) -> Path | None:
    direct = base / raw
    if direct.exists():
        return direct
    if direct.suffix:
        return None
    for suffix in (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg"):
        candidate = direct.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def _bib_files(source_file: Path, text: str) -> list[Path]:
    base = source_file.parent
    found: list[Path] = []
    for raw_group in _BIB_RE.findall(text):
        for raw in raw_group.split(","):
            clean = raw.strip()
            if clean:
                found.append(_candidate_with_suffix(base, clean, ".bib"))
    for raw in _ADDBIB_RE.findall(text):
        clean = raw.strip()
        if clean:
            found.append(_candidate_with_suffix(base, clean, ".bib"))
    return found


def _bib_diagnostics(bib_path: Path, project_root: Path) -> tuple[list[LatexDiagnostic], set[str]]:
    if not bib_path.exists():
        return ([LatexDiagnostic(
            "error",
            "missing-bibliography",
            f"Bibliography file '{bib_path.name}' was not found.",
            _relative(project_root, bib_path),
            suggestion="Check the bibliography name or Documents Root.",
        )], set())

    text = bib_path.read_text(encoding="utf-8", errors="replace")
    keys: set[str] = set()
    first_lines: dict[str, int] = {}
    diagnostics: list[LatexDiagnostic] = []

    for match in _BIB_ENTRY_RE.finditer(text):
        key = match.group(1).strip()
        line = text.count("\n", 0, match.start()) + 1
        if key in first_lines:
            diagnostics.append(LatexDiagnostic(
                "error",
                "duplicate-bib-key",
                f"Duplicate BibTeX key '{key}'.",
                _relative(project_root, bib_path),
                line,
                f"Keep one entry or rename the duplicate. First definition is near line {first_lines[key]}.",
            ))
        else:
            first_lines[key] = line
            keys.add(key)

    for match in _BIB_BLOCK_RE.finditer(text):
        key = match.group(1).strip()
        body = match.group(2)
        title_match = _TITLE_RE.search(body)
        if title_match is not None and not title_match.group(1).strip():
            line = text.count("\n", 0, match.start()) + 1
            diagnostics.append(LatexDiagnostic(
                "warning",
                "empty-bib-title",
                f"BibTeX entry '{key}' has an empty title.",
                _relative(project_root, bib_path),
                line,
                "Add the publication title before final export.",
            ))

    return diagnostics, keys


def preflight_latex(source_file: Path, *, project_root: Path, documents_root: Path) -> LatexPreflightResult:
    source_file = source_file.resolve()
    project_root = project_root.resolve()
    documents_root = documents_root.resolve()
    text = source_file.read_text(encoding="utf-8", errors="replace")
    diagnostics: list[LatexDiagnostic] = []
    source_rel = _relative(project_root, source_file)

    class_match = _DOCUMENT_CLASS_RE.search(text)
    document_class = class_match.group(1).strip() if class_match else ""
    if not class_match:
        diagnostics.append(LatexDiagnostic(
            "warning", "missing-documentclass", "No \\documentclass declaration was found.", source_rel, 1,
            "Choose a LaTeX template or add a document class declaration.",
        ))
    else:
        class_name = f"{document_class}.cls"
        if not _kpsewhich(class_name):
            diagnostics.append(LatexDiagnostic(
                "error", "missing-class", f"LaTeX document class '{class_name}' is not installed.",
                source_rel, _line_for(text, class_match.group(0)),
                f"Install the TeX package that provides {class_name}, then run the build again.",
            ))

    packages: set[str] = set()
    for match in _PACKAGE_RE.finditer(text):
        for package in match.group(1).split(","):
            clean = package.strip()
            if not clean:
                continue
            packages.add(clean)
            if not _kpsewhich(f"{clean}.sty"):
                diagnostics.append(LatexDiagnostic(
                    "error", "missing-package", f"LaTeX package '{clean}.sty' is not installed.",
                    source_rel, text.count("\n", 0, match.start()) + 1,
                    f"Install the TeX package that provides {clean}.sty.",
                ))

    if document_class.lower() == "ieeetran" and "appendix" in packages:
        diagnostics.append(LatexDiagnostic(
            "error", "ieeetran-appendix-conflict",
            "IEEEtran already provides appendix commands and conflicts with the appendix package.",
            source_rel, _line_for(text, "\\usepackage{appendix}"),
            "Remove \\usepackage{appendix} and use IEEEtran's built-in \\appendix or \\appendices commands.",
        ))
    if "natbib" in packages and "cite" in packages:
        diagnostics.append(LatexDiagnostic(
            "warning", "citation-package-overlap",
            "Both natbib and cite are loaded; they overlap in citation handling.", source_rel,
            suggestion="Keep both only if the document intentionally depends on both packages.",
        ))

    for raw in _INPUT_RE.findall(text):
        candidate = _candidate_with_suffix(source_file.parent, raw.strip(), ".tex")
        if not candidate.exists():
            diagnostics.append(LatexDiagnostic(
                "error", "missing-input", f"Included TeX file '{raw}' was not found.", source_rel,
                _line_for(text, raw), "Fix the path or add the missing file under the Documents Root.",
            ))

    for raw in _GRAPHICS_RE.findall(text):
        if _find_graphic(source_file.parent, raw.strip()) is None:
            diagnostics.append(LatexDiagnostic(
                "error", "missing-graphic", f"Referenced figure '{raw}' was not found.", source_rel,
                _line_for(text, raw), "Fix the figure path or add the asset under the Documents Root.",
            ))

    bib_keys: set[str] = set()
    for bib_path in _bib_files(source_file, text):
        bib_diagnostics, keys = _bib_diagnostics(bib_path, project_root)
        diagnostics.extend(bib_diagnostics)
        bib_keys.update(keys)

    cited_keys: set[str] = set()
    for group in _CITE_RE.findall(text):
        cited_keys.update(key.strip() for key in group.split(",") if key.strip())
    if cited_keys and not _bib_files(source_file, text):
        diagnostics.append(LatexDiagnostic(
            "warning", "citations-without-bibliography",
            "The document contains citations but no bibliography command was found.", source_rel,
            suggestion="Add \\bibliography{...} or \\addbibresource{...}.",
        ))
    elif bib_keys:
        for key in sorted(cited_keys - bib_keys):
            diagnostics.append(LatexDiagnostic(
                "warning", "missing-citation-key", f"Citation key '{key}' is not present in the referenced bibliography.",
                source_rel, _line_for(text, key), "Add the BibTeX entry or correct the citation key.",
            ))

    labels = set(_LABEL_RE.findall(text))
    for key in sorted(set(_REF_RE.findall(text)) - labels):
        diagnostics.append(LatexDiagnostic(
            "warning", "missing-label", f"Reference label '{key}' is not defined in the main document.", source_rel,
            _line_for(text, key), "Add the matching \\label or verify that it is defined in an included TeX file.",
        ))

    # Ensure the chosen source is actually inside the build/document root.
    try:
        source_file.relative_to(documents_root)
    except ValueError:
        diagnostics.insert(0, LatexDiagnostic(
            "error", "source-outside-documents-root",
            "The selected LaTeX file is outside the configured Documents Root.", source_rel,
            suggestion="Change Documents Root to contain this file, or choose a main .tex file inside it.",
        ))

    return LatexPreflightResult(tuple(_dedupe(diagnostics)))


def _dedupe(items: Iterable[LatexDiagnostic]) -> list[LatexDiagnostic]:
    seen: set[tuple[object, ...]] = set()
    output: list[LatexDiagnostic] = []
    for item in items:
        key = (item.severity, item.code, item.message, item.file, item.line)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def parse_latex_log(log: str) -> tuple[LatexDiagnostic, ...]:
    diagnostics: list[LatexDiagnostic] = []
    lines = log.splitlines()
    bibtex_failed = "Bibtex errors:" in log or "Repeated entry---line" in log

    i = 0
    while i < len(lines):
        line = lines[i]
        file_line = re.search(r"(?:^|\s)([^\s:]+\.(?:tex|bib|bbl|sty|cls)):(\d+):\s*(.*)", line)
        if file_line:
            filename, number, message = file_line.group(1), int(file_line.group(2)), file_line.group(3).strip()
            if "Missing $ inserted" in message:
                diagnostics.append(LatexDiagnostic(
                    "error", "missing-math-delimiter", "LaTeX expected math-mode syntax at this location.",
                    Path(filename).name, number,
                    "Check nearby _, ^, $, braces, or bibliography text that needs URL-safe formatting.", message,
                ))
            elif "Undefined control sequence" in message:
                diagnostics.append(LatexDiagnostic(
                    "error", "undefined-control-sequence", "LaTeX encountered an undefined command.",
                    Path(filename).name, number,
                    "Check the command spelling and whether its package is loaded.", message,
                ))
            elif "LaTeX Error:" in message:
                diagnostics.append(LatexDiagnostic(
                    "error", "latex-error", message.replace("LaTeX Error:", "").strip(),
                    Path(filename).name, number, "Open the source at this line and correct the reported LaTeX error.", message,
                ))

        missing_file = re.search(r"! LaTeX Error: File [`']([^`']+)[`'] not found", line)
        if missing_file:
            name = missing_file.group(1)
            diagnostics.append(LatexDiagnostic(
                "error", "missing-tex-file", f"LaTeX dependency '{name}' was not found.",
                suggestion=f"Install or add the file that provides {name}.", detail=line.strip(),
            ))

        command_conflict = re.search(r"Command \\([^\s]+) already defined", line)
        if command_conflict:
            command = command_conflict.group(1)
            diagnostics.append(LatexDiagnostic(
                "error", "command-conflict", f"LaTeX command \\{command} is defined more than once.",
                suggestion="Check for conflicting document-class and package definitions.", detail=line.strip(),
            ))

        repeated = re.search(r"Repeated entry---line\s+(\d+)\s+of file\s+(.+)$", line)
        if repeated:
            key = ""
            for lookahead in lines[i + 1:i + 4]:
                key_match = re.search(r"@\w+\{([^,\s]+)", lookahead)
                if key_match:
                    key = key_match.group(1)
                    break
            diagnostics.append(LatexDiagnostic(
                "error", "duplicate-bib-key",
                f"Duplicate BibTeX key '{key}'." if key else "Duplicate BibTeX entry.",
                Path(repeated.group(2).strip()).name, int(repeated.group(1)),
                "Keep one entry or rename the duplicate key.", line.strip(),
            ))

        empty_title = re.search(r"Warning--empty title in\s+(.+)$", line)
        if empty_title:
            diagnostics.append(LatexDiagnostic(
                "warning", "empty-bib-title", f"BibTeX entry '{empty_title.group(1).strip()}' has an empty title.",
                suggestion="Add the publication title before final export.", detail=line.strip(),
            ))

        citation = re.search(r"Citation [`']([^`']+)[`'].*undefined", line)
        if citation:
            diagnostics.append(LatexDiagnostic(
                "warning", "undefined-citation", f"Citation '{citation.group(1)}' is unresolved.",
                suggestion=("Fix the primary BibTeX error first; this citation warning is probably downstream."
                            if bibtex_failed else "Verify the citation key and rerun the complete bibliography build."),
                detail=line.strip(), secondary=bibtex_failed,
            ))

        reference = re.search(r"Reference [`']([^`']+)[`'].*undefined", line)
        if reference:
            diagnostics.append(LatexDiagnostic(
                "warning", "undefined-reference", f"Reference '{reference.group(1)}' is unresolved.",
                suggestion="Verify the matching \\label and rerun LaTeX enough times to resolve references.",
                detail=line.strip(), secondary=True,
            ))

        if "Runaway argument?" in line:
            diagnostics.append(LatexDiagnostic(
                "error", "runaway-argument", "LaTeX found an unterminated or malformed command argument.",
                suggestion="Inspect the lines immediately before the reported failure for mismatched {}, [] or a malformed citation.",
                detail=line.strip(),
            ))
        i += 1

    deduped = _dedupe(diagnostics)
    if any(item.severity == "error" and not item.secondary for item in deduped):
        deduped = [
            replace(item, secondary=True)
            if item.code in {"undefined-citation", "undefined-reference"}
            else item
            for item in deduped
        ]
    return tuple(deduped)
