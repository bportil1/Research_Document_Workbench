from __future__ import annotations

import tempfile
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from tech_documents.api import DocumentEngine
from tech_documents.latex_tools import parse_latex_log


class LatexDirectoryContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "workbench"
        self.engine = DocumentEngine(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def test_link_existing_repo_and_set_documents_root(self):
        repo = Path(self.temp.name) / "repo"
        overleaf = repo / "overleaf"
        overleaf.mkdir(parents=True)
        (overleaf / "main.tex").write_text("\\documentclass{article}\n\\begin{document}x\\end{document}\n", encoding="utf-8")
        (repo / ".git").mkdir()
        (repo / ".git" / "noise").write_text("hidden", encoding="utf-8")

        name = self.engine.link_project(repo)
        context = self.engine.set_project_context(name, documents_root="overleaf", main_tex="overleaf/main.tex")

        self.assertEqual(context["project_root"], str(repo.resolve()))
        self.assertEqual(context["documents_root"], "overleaf")
        self.assertEqual(context["build_root"], str(overleaf.resolve()))
        self.assertEqual(context["main_tex"], "overleaf/main.tex")
        listed = next(project for project in self.engine.list_projects() if project["name"] == name)
        self.assertTrue(listed["linked"])
        self.assertFalse(any(node["name"] == ".git" for node in listed["tree"]))

        self.engine.delete_project(name)
        self.assertTrue(repo.exists(), "Removing an attached project must never delete the external folder")

    def test_create_ieee_latex_project_and_make_it_documents_root(self):
        project = self.engine.create_project("research")
        result = self.engine.create_latex_project(
            project,
            directory="overleaf",
            template="ieee-conference",
            title="Interpretable Models",
            authors="A. Researcher",
        )
        root = self.engine.project_path(project)
        main = root / result["main_tex"]
        text = main.read_text(encoding="utf-8")
        self.assertIn("\\documentclass[conference]{IEEEtran}", text)
        self.assertIn("\\usepackage{booktabs}", text)
        self.assertIn("\\usepackage{url}", text)
        self.assertTrue((root / "overleaf" / "bib.bib").exists())
        self.assertTrue((root / "overleaf" / "images").is_dir())
        self.assertEqual(self.engine.project_context(project)["documents_root"], "overleaf")

    @mock.patch("tech_documents.latex_tools._kpsewhich", return_value=True)
    def test_preflight_surfaces_duplicate_bib_keys_and_missing_citation(self, _kpsewhich):
        project = self.engine.create_project("paper")
        root = self.engine.project_path(project)
        (root / "paper.tex").write_text(
            "\\documentclass{article}\n"
            "\\usepackage{booktabs}\n"
            "\\begin{document}\\cite{known,missing}\\bibliographystyle{plain}\\bibliography{references}\\end{document}\n",
            encoding="utf-8",
        )
        (root / "references.bib").write_text(
            "@article{known, title={One}, year={2026}}\n"
            "@article{known, title={Two}, year={2025}}\n",
            encoding="utf-8",
        )
        result = self.engine.latex_preflight(project, "paper.tex")
        codes = [item["code"] for item in result["diagnostics"]]
        self.assertIn("duplicate-bib-key", codes)
        self.assertIn("missing-citation-key", codes)
        self.assertFalse(result["ok"])


    @mock.patch("tech_documents.latex_tools._kpsewhich", return_value=True)
    def test_preflight_catches_ieeetran_appendix_conflict(self, _kpsewhich):
        project = self.engine.create_project("ieee")
        root = self.engine.project_path(project)
        (root / "paper.tex").write_text(
            "\\documentclass{IEEEtran}\n"
            "\\usepackage{appendix}\n"
            "\\begin{document}x\\end{document}\n",
            encoding="utf-8",
        )
        result = self.engine.latex_preflight(project, "paper.tex")
        self.assertIn("ieeetran-appendix-conflict", [item["code"] for item in result["diagnostics"]])
        self.assertFalse(result["ok"])

    @mock.patch("tech_documents.latex_tools._kpsewhich", return_value=True)
    @mock.patch("tech_documents.api.shutil.which", side_effect=lambda name: "/usr/bin/latexmk" if name == "latexmk" else None)
    def test_compile_uses_documents_root_not_repository_root(self, _which, _kpsewhich):
        repo = Path(self.temp.name) / "repo"
        overleaf = repo / "overleaf"
        overleaf.mkdir(parents=True)
        (repo / "outside.txt").write_text("do not need this for build root semantics", encoding="utf-8")
        (overleaf / "main.tex").write_text("\\documentclass{article}\\begin{document}ok\\end{document}", encoding="utf-8")
        name = self.engine.link_project(repo)
        self.engine.set_project_context(name, documents_root="overleaf", main_tex="overleaf/main.tex")

        def fake_compile(source_file: Path, output_dir: Path):
            self.assertEqual(source_file.name, "main.tex")
            self.assertEqual(source_file.parent.name, "source")
            self.assertFalse((source_file.parent / "outside.txt").exists())
            (output_dir / "main.pdf").write_bytes(b"%PDF-fake")
            return subprocess.CompletedProcess(["latexmk"], 0, stdout="ok", stderr="")

        with mock.patch("tech_documents.api.compile_with_latexmk", side_effect=fake_compile):
            result = self.engine.compile_latex(name, "overleaf/main.tex")
        self.assertTrue(result.ok)

    @mock.patch("tech_documents.latex_tools._kpsewhich", return_value=True)
    @mock.patch("tech_documents.api.shutil.which", side_effect=lambda name: "/usr/bin/latexmk" if name == "latexmk" else None)
    def test_compile_latex_path_preserves_host_facing_api(self, _which, _kpsewhich):
        repo = Path(self.temp.name) / "host-owned-repo"
        repo.mkdir()
        (repo / "paper.tex").write_text(
            "\\documentclass{article}\n\\begin{document}host\\end{document}\n",
            encoding="utf-8",
        )
        external_builds = Path(self.temp.name) / "host-builds"

        def fake_compile(source_file: Path, output_dir: Path):
            self.assertEqual(source_file, source_file.parent / "paper.tex")
            self.assertEqual(source_file.parent.name, "source")
            self.assertEqual(output_dir.parent.parent, external_builds)
            (output_dir / "paper.pdf").write_bytes(b"%PDF-fake")
            return subprocess.CompletedProcess(["latexmk"], 0, stdout="ok", stderr="")

        with mock.patch("tech_documents.api.compile_with_latexmk", side_effect=fake_compile):
            result = self.engine.compile_latex_path(repo, "paper.tex", builds_dir=external_builds)
        self.assertTrue(result.ok)
        self.assertEqual(result.status_code, 200)


class LatexDiagnosticParserTests(unittest.TestCase):
    def test_bibtex_primary_error_demotes_undefined_citations(self):
        log = """Repeated entry---line 298 of file bib.bib
 : @inproceedings{sundararajan2017axiomatic
Bibtex errors: See file main.blg
Package natbib Warning: Citation `rudin2019stop' on page 1 undefined
"""
        diagnostics = parse_latex_log(log)
        duplicate = next(item for item in diagnostics if item.code == "duplicate-bib-key")
        citation = next(item for item in diagnostics if item.code == "undefined-citation")
        self.assertEqual(duplicate.file, "bib.bib")
        self.assertEqual(duplicate.line, 298)
        self.assertFalse(duplicate.secondary)
        self.assertTrue(citation.secondary)

    def test_primary_latex_error_demotes_unresolved_citation_noise(self):
        log = """Package natbib Warning: Citation `rudin2019stop' on page 1 undefined
./main.bbl:120: Missing $ inserted.
"""
        diagnostics = parse_latex_log(log)
        primary = [item for item in diagnostics if not item.secondary]
        self.assertEqual([item.code for item in primary], ["missing-math-delimiter"])


class LatexFrontendContractTests(unittest.TestCase):
    def test_directory_context_diagnostics_and_navigation_controls_are_present(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "tech_documents" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
        js = (root / "tech_documents" / "web" / "static" / "app.js").read_text(encoding="utf-8")
        css = (root / "tech_documents" / "web" / "static" / "styles.css").read_text(encoding="utf-8")

        for element_id in (
            "projectContextBtn", "attachProjectBtn", "changeProjectRootBtn", "newLatexProjectBtn",
            "contextProjectRoot", "contextDocumentsRoot", "contextBuildRoot",
            "buildDiagnostics", "toggleRawLogBtn", "minimizeBuildDiagnosticsBtn", "goTopBtn", "goLineBtn", "goBottomBtn",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("renderBuildDiagnostics", js)
        self.assertIn("setBuildDiagnosticsCollapsed", js)
        self.assertIn("toggleBuildDiagnosticsCollapsed", js)
        self.assertIn("changeProjectRootFromContext", js)
        self.assertIn("openAttachProjectDialog(true)", js)
        self.assertIn("New Project Root selected", js)
        self.assertIn(".workbench-path-control", css)
        self.assertIn("compileCurrentFile(force = false)", js)
        self.assertIn(".editor-statusbar", css)
        self.assertIn(".build-diagnostics.collapsed", css)
        self.assertIn("overflow: hidden", css)


if __name__ == "__main__":
    unittest.main()
