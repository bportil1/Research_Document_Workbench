#!/usr/bin/env python3
"""Offline PS-13 acceptance smoke for the presentation subsystem.

Only local files and tools are used. This intentionally does not install
packages, download themes, run notebooks or execute imported Makefiles.
Run only with Beamer archives that you trust (LaTeX is not a sandbox).
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

# Accept invocation from anywhere, without changing the installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tech_documents import DocumentEngine
from tech_documents.presentations import StyleReference


def run() -> int:
    parser = argparse.ArgumentParser(description="Local-only presentation integration acceptance checks")
    parser.add_argument("--reference-zip", type=Path, help="Trusted local Beamer theme/project ZIP, e.g. csci447.zip")
    parser.add_argument("--run-tests", action="store_true", help="Run the complete repository unittest suite")
    args = parser.parse_args()
    print("PS-13 local presentation preflight (no network access)")
    for name in ("quarto", "latexmk", "pdflatex", "pdftoppm", "node"):
        print(f"  {name}: {shutil.which(name) or 'unavailable'}")
    print(f"  Flask: {'available' if importlib.util.find_spec('flask') else 'unavailable'}")
    failures = []
    skipped = []
    if args.run_tests:
        print("\nRunning complete local Python tests ...", flush=True)
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                                cwd=Path(__file__).resolve().parents[1], check=False)
        if result.returncode:
            failures.append("unittest suite")
    with tempfile.TemporaryDirectory(prefix="presentation-ps13-acceptance-") as temp:
        base = Path(temp)
        engine = DocumentEngine(base / "workbench")
        try:
            project = engine.create_project("acceptance")
            engine.create_file(project, "sample.slides.md", "# Offline Presentation\n\n---\n\n# Content\n\n\\(x^2+y^2\\)\n")
            try:
                source = engine.project_path(project) / "sample.slides.md"
                original = source.read_bytes()
                converted = engine.export_presentation(project, "sample.slides.md", conversion_target="notebook")
                if not (engine.project_path(project) / converted["path"]).is_file() or source.read_bytes() != original:
                    raise RuntimeError("conversion did not preserve its input")
                engine.save_presentation_profile(project, "sample.slides.md", renderer_id="reveal", output_format="html")
                if engine.presentation_profile(project, "sample.slides.md")["renderer_id"] != "reveal":
                    raise RuntimeError("presentation profile was not persisted")
                print("  Source-preserving conversion and saved profile: PASS")
            except Exception as exc:
                failures.append(f"conversion/profile check: {exc}")
            inspected = None
            reference = None
            if args.reference_zip is not None:
                archive = args.reference_zip.expanduser().resolve()
                if not archive.is_file() or archive.suffix.lower() != ".zip":
                    failures.append("reference ZIP missing or invalid")
                else:
                    try:
                        inspected = engine.inspect_beamer_styles(archive)
                        print(f"  Beamer ZIP inspection: {len(inspected['themes'])} theme(s), "
                              f"{len(inspected['project_entrypoints'])} entrypoint(s)")
                        installed = engine.import_beamer_style(archive, version="acceptance.1")
                        reference = StyleReference(installed["identifier"], installed["version"], "beamer")
                        print(f"  Beamer ZIP import: PASS ({reference.identifier}@{reference.version})")
                    except Exception as exc:
                        failures.append(f"reference theme import: {exc}")
            if reference is not None:
                if shutil.which("pdflatex") and shutil.which("pdftoppm"):
                    try:
                        result = engine.presentation_style_preview(reference, generate=True)
                        if not result["cached"] or len(result["pages"]) < 2:
                            raise RuntimeError("expected a two-slide rendered preview")
                        print("  Real Beamer theme PDF + PNG preview: PASS")
                    except Exception as exc:
                        failures.append(f"Beamer preview: {exc}")
                else:
                    skipped.append("real Beamer preview (requires pdflatex and pdftoppm)")
            if shutil.which("quarto"):
                for renderer, output, style in (
                    ("reveal", "html", None),
                    ("powerpoint", "pptx", None),
                    ("beamer", "pdf", reference),
                ):
                    if renderer == "beamer" and not (shutil.which("latexmk") or shutil.which("pdflatex")):
                        skipped.append("Quarto Beamer PDF (TeX unavailable)")
                        continue
                    try:
                        result = engine.export_presentation(project, "sample.slides.md",
                                                            renderer_id=renderer, output_format=output,
                                                            style=style, output_name=f"ps13-{renderer}")
                        path = engine.project_path(project) / result["path"]
                        if not path.is_file() or path.stat().st_size == 0:
                            raise RuntimeError("renderer returned no output artifact")
                        print(f"  Real Quarto {renderer}/{output} export: PASS")
                    except Exception as exc:
                        failures.append(f"Quarto {renderer}/{output}: {exc}")
            else:
                skipped.append("real Quarto Markdown rendering (Quarto unavailable)")
        finally:
            engine.notebooks.shutdown_all()
    for reason in skipped:
        print(f"  SKIP: {reason}")
    for reason in failures:
        print(f"  FAIL: {reason}", file=sys.stderr)
    print("PS-13 acceptance:", "FAIL" if failures else "PASS for available checks",
          f"({len(skipped)} skipped)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
