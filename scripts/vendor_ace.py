#!/usr/bin/env python3
"""Vendor the pinned Ace browser distribution for notebook code cells."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

ACE_VERSION = "1.44.0"
ARCHIVE_URL = f"https://github.com/ajaxorg/ace-builds/archive/refs/tags/v{ACE_VERSION}.zip"
ROOT = Path(__file__).resolve().parent.parent
DESTINATION = ROOT / "tech_documents" / "web" / "static" / "vendor" / "ace"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rdw-ace-") as temp_dir:
        temp = Path(temp_dir)
        archive = temp / "ace-builds.zip"
        print(f"Downloading Ace {ACE_VERSION}...")
        urllib.request.urlretrieve(ARCHIVE_URL, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(temp)
        source = temp / f"ace-builds-{ACE_VERSION}" / "src-min-noconflict"
        if not source.exists():
            raise SystemExit("Ace archive did not contain src-min-noconflict.")
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, DESTINATION)
    print(f"Vendored Ace {ACE_VERSION} into {DESTINATION.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
