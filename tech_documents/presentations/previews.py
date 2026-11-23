"""PS-09: renderer-specific, on-demand, local presentation theme previews.

Previewing Beamer executes imported TeX macros in a local TeX engine. The
-no-shell-escape flag helps, but is NOT a sandbox. Explicit user action and
trusted themes remain prerequisites. Nothing is fetched from the network.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Protocol

from .beamer_rendering import stage_beamer_style
from .models import PresentationError, StyleReference
from .profiles import style_manifest_digest
from .style_registry import InstalledStyle, PresentationStyleRegistry


_PREVIEW_FILES = ("preview.pdf", "slide-1.png", "slide-2.png")
_MAX_PDF_BYTES = 20 * 1024 * 1024
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


class PreviewProvider(Protocol):
    """Future Reveal.js / PowerPoint providers use the same API and cache."""

    style_kind: str

    def availability(self) -> tuple[bool, str]: ...

    def render(self, installed: InstalledStyle, destination: Path) -> None: ...


class BeamerPreviewProvider:
    """Compile a fixed two-slide sample; rasterize both pages with pdftoppm."""

    style_kind = "beamer"

    def availability(self) -> tuple[bool, str]:
        if not shutil.which("pdflatex"):
            return False, "Install local pdflatex (TeX Live) to preview Beamer themes."
        if not shutil.which("pdftoppm"):
            return False, "Install local pdftoppm (Poppler) to produce slide thumbnails."
        return True, ""

    @staticmethod
    def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None,
             timeout: int = 90) -> None:
        try:
            result = subprocess.run(command, cwd=str(cwd), env=env,
                                    capture_output=True, text=True, errors="replace",
                                    check=False, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise PresentationError("Theme preview rendering timed out.") from exc
        except OSError as exc:
            raise PresentationError(f"Unable to start local preview renderer: {exc}") from exc
        if result.returncode:
            log = (result.stderr or result.stdout or "Local preview tool failed.").strip()
            raise PresentationError(f"Theme preview failed: {log[-2500:]}")

    def render(self, installed: InstalledStyle, destination: Path) -> None:
        reference = installed.manifest.reference
        # This intentionally does not use a presentation's source or project files.
        with tempfile.TemporaryDirectory(prefix="rdw-preview-build-") as temp:
            build = Path(temp)
            with stage_beamer_style(self._registry, reference) as staged:
                sample = build / "preview.tex"
                sample.write_text(
                    r"\documentclass[aspectratio=169]{beamer}" "\n"
                    + r"\usetheme{" + staged.theme_name + "}\n"
                    + r"\title{Presentation Style Preview}" "\n"
                    + r"\subtitle{Reusable Beamer Theme}" "\n"
                    + r"\author{Research Document Workbench}" "\n"
                    + r"\date{}" "\n"
                    + r"\begin{document}" "\n"
                    + r"\begin{frame}\titlepage\end{frame}" "\n"
                    + r"\begin{frame}{Content and Mathematics}" "\n"
                    + r"\begin{itemize}\item First idea\item Second idea\end{itemize}" "\n"
                    + r"\[ I(X;Y)=\sum_{x,y}p(x,y)\log\frac{p(x,y)}{p(x)p(y)} \]" "\n"
                    + r"\end{frame}" "\n"
                    + r"\end{document}" "\n",
                    encoding="utf-8",
                )
                # No shell-escape; never execute imported Makefiles or custom scripts.
                command = [shutil.which("pdflatex") or "pdflatex", "-no-shell-escape",
                           "-interaction=nonstopmode", "-halt-on-error", "preview.tex"]
                self._run(command, cwd=build, env=dict(staged.environ))
                # Second pass resolves totals/navigation of some themes.
                self._run(command, cwd=build, env=dict(staged.environ))
            pdf = build / "preview.pdf"
            if not pdf.is_file() or pdf.is_symlink() or not 0 < pdf.stat().st_size <= _MAX_PDF_BYTES:
                raise PresentationError("Preview PDF is missing or exceeds the maximum size.")
            destination.mkdir()
            shutil.copyfile(pdf, destination / "preview.pdf")
            for number in (1, 2):
                self._run([
                    shutil.which("pdftoppm") or "pdftoppm", "-f", str(number), "-l", str(number),
                    "-singlefile", "-scale-to", "960", "-png", str(pdf),
                    str(destination / f"slide-{number}"),
                ], cwd=build, timeout=45)
                image = destination / f"slide-{number}.png"
                if not image.is_file() or image.is_symlink() or not 0 < image.stat().st_size <= _MAX_IMAGE_BYTES:
                    raise PresentationError("Preview image is missing or exceeds the maximum size.")

    def bind_registry(self, registry: PresentationStyleRegistry) -> None:
        self._registry = registry


@dataclass(frozen=True)
class PreviewStatus:
    available: bool
    reason: str
    cached: bool
    fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {"available": self.available, "reason": self.reason,
                "cached": self.cached, "fingerprint": self.fingerprint,
                "pages": ["slide-1.png", "slide-2.png"] if self.cached else [],
                "pdf": "preview.pdf" if self.cached else None}


class PresentationPreviewService:
    """Immutable-version preview cache; no rendering on lookup or file retrieval."""

    def __init__(self, registry: PresentationStyleRegistry, root: str | Path,
                 providers: tuple[PreviewProvider, ...] | None = None) -> None:
        self.registry = registry
        self.root = Path(root).expanduser().absolute()
        self._providers: dict[str, PreviewProvider] = {}
        for provider in providers if providers is not None else (BeamerPreviewProvider(),):
            self.register(provider)

    def register(self, provider: PreviewProvider) -> None:
        if provider.style_kind in self._providers:
            raise PresentationError("Preview provider is already registered for this style kind.")
        if isinstance(provider, BeamerPreviewProvider):
            provider.bind_registry(self.registry)
        self._providers[provider.style_kind] = provider

    def _cache(self, reference: StyleReference, fingerprint: str) -> Path:
        name = hashlib.sha256(
            f"{reference.kind}:{reference.identifier}:{reference.version}:{fingerprint}".encode("utf-8")
        ).hexdigest()
        return self.root / name

    def _installed(self, reference: StyleReference) -> tuple[InstalledStyle, str]:
        installed = self.registry.resolve(reference)
        return installed, style_manifest_digest(installed.manifest)

    @staticmethod
    def _is_complete(folder: Path) -> bool:
        if folder.is_symlink() or not folder.is_dir():
            return False
        return all((folder / name).is_file() and not (folder / name).is_symlink()
                   and 0 < (folder / name).stat().st_size <= (_MAX_PDF_BYTES if name.endswith(".pdf") else _MAX_IMAGE_BYTES)
                   for name in _PREVIEW_FILES)

    def status(self, reference: StyleReference) -> PreviewStatus:
        _, digest = self._installed(reference)
        provider = self._providers.get(reference.kind)
        ready, reason = provider.availability() if provider else (False, "No preview provider for this style type yet.")
        folder = self._cache(reference, digest)
        if self.root.is_symlink() or folder.is_symlink():
            raise PresentationError("Preview storage cannot contain symlinks.")
        cached = self._is_complete(folder)
        return PreviewStatus(ready, reason, cached, digest)

    def generate(self, reference: StyleReference) -> PreviewStatus:
        installed, digest = self._installed(reference)
        provider = self._providers.get(reference.kind)
        available, reason = provider.availability() if provider else (False, "No preview provider for this style type yet.")
        if not available or provider is None:
            raise PresentationError(reason)
        if self.root.is_symlink():
            raise PresentationError("Preview storage cannot be a symlink.")
        self.root.mkdir(parents=True, exist_ok=True)
        folder = self._cache(reference, digest)
        if folder.is_symlink():
            raise PresentationError("Preview storage cannot contain symlinks.")
        if not self._is_complete(folder):
            with tempfile.TemporaryDirectory(prefix=".preview-", dir=self.root) as temp:
                working = Path(temp) / "completed"
                provider.render(installed, working)
                if not self._is_complete(working):
                    raise PresentationError("Preview provider returned incomplete output.")
                # A version's cache is never used for a different manifest hash.
                if folder.exists():
                    if folder.is_symlink() or not folder.is_dir():
                        raise PresentationError("Preview cache path is not a normal directory.")
                    shutil.rmtree(folder)
                working.rename(folder)
        return PreviewStatus(True, "", True, digest)

    def file(self, reference: StyleReference, filename: str) -> Path:
        if filename not in _PREVIEW_FILES:
            raise PresentationError("Unknown presentation preview asset.")
        _, digest = self._installed(reference)
        folder = self._cache(reference, digest)
        if self.root.is_symlink() or folder.is_symlink() or not self._is_complete(folder):
            raise PresentationError("Theme preview has not been generated.", status_code=404)
        return folder / filename
