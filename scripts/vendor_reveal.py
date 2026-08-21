#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

VERSION = "5.2.1"
ARCHIVE_URL = f"https://github.com/hakimel/reveal.js/archive/refs/tags/{VERSION}.zip"
ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tech_documents" / "web" / "static" / "vendor" / "reveal"


def main() -> None:
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        archive = temp_path / "reveal.zip"
        print(f"Downloading Reveal.js {VERSION} from the official release tag...")
        urllib.request.urlretrieve(ARCHIVE_URL, archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(temp_path / "src")
        source = temp_path / "src" / f"reveal.js-{VERSION}"
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        DESTINATION.mkdir(parents=True)
        shutil.copytree(source / "dist", DESTINATION / "dist")
        shutil.copytree(source / "plugin", DESTINATION / "plugin")
        (DESTINATION / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    print(f"Vendored Reveal.js {VERSION} into {DESTINATION}")


if __name__ == "__main__":
    main()
