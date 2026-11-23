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
    """Refresh build sources while preserving compiler intermediates.

    The source snapshot is replaced on every build so deleted/renamed project
    files cannot linger in the build tree.  The output directory is deliberately
    retained for a stable ``build_id`` so latexmk/Tectonic can reuse auxiliary
    files between preview builds.
    """
    build_root = builds_dir / build_id
    source_dir = build_root / "source"
    output_dir = build_root / "output"
    build_root.mkdir(parents=True, exist_ok=True)
    if source_dir.exists():
        shutil.rmtree(source_dir)
    shutil.copytree(
        project_path,
        source_dir,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"
        ),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return source_dir, output_dir


def compile_with_latexmk(
    source_file: Path, output_dir: Path, *, env: dict[str, str] | None = None,
    no_shell_escape: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        "latexmk",
        "-pdf",
        "-file-line-error",
        "-interaction=nonstopmode",
        "-halt-on-error",
        *(["-no-shell-escape"] if no_shell_escape else []),
        f"-output-directory={output_dir}",
        source_file.name,
    ]
    return subprocess.run(
        command,
        cwd=source_file.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def compile_with_tectonic(
    source_file: Path, output_dir: Path, *, env: dict[str, str] | None = None,
    no_network: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [
        "tectonic",
        *(["--only-cached"] if no_network else []),
        "--keep-logs",
        "--keep-intermediates",
        "--outdir",
        str(output_dir),
        source_file.name,
    ]
    return subprocess.run(
        command,
        cwd=source_file.parent,
        env=env,
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
