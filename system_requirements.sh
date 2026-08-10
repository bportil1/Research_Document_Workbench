#!/usr/bin/bash
set -e

sudo apt update

sudo apt install -y \
    latexmk \
    texlive-latex-extra \
    texlive-science \
    texlive-bibtex-extra \
    biber
