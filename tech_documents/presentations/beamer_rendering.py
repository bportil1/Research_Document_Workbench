"""PS-05: stage a verified Beamer theme for one local Quarto render.

The staging folder is temporary and never contains presentation source files.
This is resource isolation, NOT a security sandbox for untrusted TeX code.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Iterator, Mapping

from .models import PresentationError, StyleReference
from .style_registry import PresentationStyleRegistry

_THEME_NAME = re.compile(r"beamertheme([A-Za-z0-9_-]+)\.sty\Z")


@dataclass(frozen=True)
class BeamerBuildEnvironment:
    """Renderer settings for a *single* pinned and verified theme version."""

    theme_name: str
    environ: Mapping[str, str]


@contextmanager
def stage_beamer_style(
    registry: PresentationStyleRegistry, reference: StyleReference,
) -> Iterator[BeamerBuildEnvironment]:
    """Copy only registered assets and expose them to local TeX via TEXINPUTS.

    A scratch copy prevents a renderer from writing into immutable registry
    packages. TEXINPUTS recursively searches nested theme asset directories;
    the trailing path separator retains TeX's system search directories.
    """
    if reference.kind != "beamer":
        raise PresentationError("Selected presentation style is not a Beamer theme.")
    installed = registry.resolve(reference, renderer_id="beamer")
    manifest = installed.manifest
    match = _THEME_NAME.fullmatch(Path(manifest.entrypoint).name)
    if not manifest.entrypoint or not match or manifest.entrypoint not in {a.path for a in manifest.assets}:
        raise PresentationError("Selected style does not declare a usable beamertheme*.sty entrypoint.")
    with tempfile.TemporaryDirectory(prefix="rdw-beamer-style-") as temp:
        assets_dir = Path(temp) / "assets"
        assets_dir.mkdir()
        for asset in manifest.assets:
            source = installed.asset(asset.path)
            destination = assets_dir / asset.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as incoming, destination.open("xb") as outgoing:
                for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > asset.size:
                        raise PresentationError("Theme asset changed while preparing the build.")
                    digest.update(chunk)
                    outgoing.write(chunk)
            if size != asset.size or digest.hexdigest() != asset.sha256:
                raise PresentationError("Theme asset failed integrity verification during staging.")
        environ = os.environ.copy()
        # A final empty component restores the normal TeX system paths.
        existing = environ.get("TEXINPUTS", "")
        environ["TEXINPUTS"] = f"{assets_dir.as_posix()}//{os.pathsep}{existing}"
        yield BeamerBuildEnvironment(match.group(1), environ)
