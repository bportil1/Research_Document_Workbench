from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class CompilationResult:
    ok: bool
    status_code: int
    build_id: str = ""
    pdf_path: Path | None = None
    log: str = ""
    error: str = ""
    diagnostics: tuple[dict[str, object], ...] = field(default_factory=tuple)
    preflight: dict[str, object] = field(default_factory=dict)


def prepare_build_workspace(project_path: Path, builds_dir: Path, build_id: str) -> tuple[Path, Path]:
    """Copy a complete project into an isolated build workspace."""
    build_root = builds_dir / build_id
    source_dir = build_root / "source"
    output_dir = build_root / "output"
    shutil.copytree(
        project_path,
        source_dir,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"
        ),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return source_dir, output_dir


def compile_with_latexmk(source_file: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    command = [
        "latexmk",
        "-pdf",
        "-file-line-error",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={output_dir}",
        source_file.name,
    ]
    return subprocess.run(
        command,
        cwd=source_file.parent,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def compile_with_tectonic(source_file: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    command = [
        "tectonic",
        "--keep-logs",
        "--keep-intermediates",
        "--outdir",
        str(output_dir),
        source_file.name,
    ]
    return subprocess.run(
        command,
        cwd=source_file.parent,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def available_compilers() -> dict[str, bool]:
    return {
        "latexmk": bool(shutil.which("latexmk")),
        "tectonic": bool(shutil.which("tectonic")),
    }
