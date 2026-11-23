"""PS-13 local-only acceptance tests for the unified presentation workflow.

No network or remote rendering is used. Toolchain-specific tests report a
skip when optional locally installed dependencies are unavailable.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_documents import DocumentEngine
from tech_documents.presentations import PresentationError, StyleReference
from tech_documents.presentations.legacy_adapters import presentation_output_stem


class PresentationFinalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.engine = DocumentEngine(self.base / "workbench")
        self.addCleanup(self.engine.notebooks.shutdown_all)
        self.project = self.engine.create_project("research")
        self.root = self.engine.project_path(self.project)
        for directory in ("paper", "defense"):
            self.engine.create_folder(self.project, directory)
            self.engine.create_file(self.project, f"{directory}/talk.slides.md", f"# {directory}\n")
            self.engine.create_file(self.project, f"{directory}/talk.ipynb")

    def _quarto_simulator(self, args, **kwargs):
        self.assertIn("--no-execute", args)
        if args[args.index("--to") + 1] == "revealjs":
            self.assertIn("embed-resources:true", args)
        path = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(args[2]).read_bytes()[:64])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def test_default_names_isolate_nested_markdown_and_root_compatibility(self):
        self.engine.create_file(self.project, "talk.slides.md", "# root")
        root = self.root / "talk.slides.md"
        self.assertEqual(presentation_output_stem(root, self.root), "talk")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="/local/quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=self._quarto_simulator):
            outputs = [self.engine.export_presentation(self.project, name, renderer_id="reveal", output_format="html")
                       for name in ("paper/talk.slides.md", "defense/talk.slides.md", "talk.slides.md")]
        paths = [row["path"] for row in outputs]
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual(paths[-1], "builds/presentations/talk.html")
        for path in paths:
            self.assertTrue((self.root / path).is_file())
        self.assertNotEqual((self.root / paths[0]).read_bytes(), (self.root / paths[1]).read_bytes())
        self.assertEqual((self.root / "paper/talk.slides.md").read_text(), "# paper\n")

    def test_nested_notebooks_pass_distinct_names_into_original_exporter(self):
        seen = []
        def fake_export(source, *, project_root, format_id, output_name):
            seen.append(output_name)
            file = project_root / "builds" / "notebooks" / (output_name + ".html")
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(source.parent.name)
            return {"path": file.relative_to(project_root).as_posix(), "size": file.stat().st_size}
        capabilities = self.engine.notebook_exports.capabilities()
        reveal = next(item for item in capabilities["formats"] if item["id"] == "reveal")
        reveal["available"] = True
        reveal["reason"] = ""
        with patch.object(self.engine.notebook_exports, "export", side_effect=fake_export), \
             patch.object(self.engine.notebook_exports, "capabilities", return_value=capabilities), \
             patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"):
            first = self.engine.export_presentation(self.project, "paper/talk.ipynb", renderer_id="reveal", output_format="html")
            second = self.engine.export_presentation(self.project, "defense/talk.ipynb", renderer_id="reveal", output_format="html")
        self.assertEqual(len(set(seen)), 2)
        self.assertNotEqual(first["path"], second["path"])

    def test_conversion_and_document_exports_use_source_specific_defaults(self):
        first = self.engine.export_presentation(self.project, "paper/talk.slides.md", conversion_target="notebook")
        second = self.engine.export_presentation(self.project, "defense/talk.slides.md", conversion_target="notebook")
        self.assertNotEqual(first["path"], second["path"])
        self.assertTrue((self.root / first["path"]).is_file())
        self.assertTrue((self.root / second["path"]).is_file())
        chosen = []
        def document_export(project, filename, *, format_id, output_name):
            chosen.append(output_name)
            return {"path": "builds/notebooks/" + output_name + ".html", "size": 1}
        with patch.object(self.engine, "export_notebook", side_effect=document_export):
            self.engine.export_presentation(self.project, "paper/talk.ipynb", document_format="html")
            self.engine.export_presentation(self.project, "defense/talk.ipynb", document_format="html")
        self.assertEqual(len(set(chosen)), 2)

    def test_quarto_notebook_exports_preserve_stored_results_and_prior_output(self):
        service = self.engine.notebook_exports
        destination = self.root / "builds/notebooks/saved.pdf"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"previous PDF")
        notebook = self.root / "paper/talk.ipynb"
        def fake_render(args, **kwargs):
            self.assertIn("--no-execute", args)
            output = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
            output.write_bytes(b"partial PDF")
            return subprocess.CompletedProcess(args, 1, "", "simulated Quarto failure")
        with patch.object(service, "_quarto", return_value="quarto"), \
             patch("tech_documents.notebook_exports.subprocess.run", side_effect=fake_render):
            with self.assertRaisesRegex(Exception, "simulated Quarto failure"):
                service._export_quarto(notebook, destination, "pdf")
        self.assertEqual(destination.read_bytes(), b"previous PDF")
        def success(args, **kwargs):
            self.assertIn("--no-execute", args)
            output = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
            output.write_bytes(b"%PDF-1.7\nnew")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(service, "_quarto", return_value="quarto"), \
             patch("tech_documents.notebook_exports.subprocess.run", side_effect=success):
            service._export_quarto(notebook, destination, "pdf")
        self.assertTrue(destination.read_bytes().startswith(b"%PDF-1.7"))
        self.assertEqual(sorted(x.name for x in destination.parent.iterdir()), ["saved.pdf"])

    def test_explicit_output_names_remain_unchanged(self):
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=self._quarto_simulator):
            result = self.engine.export_presentation(self.project, "paper/talk.slides.md", renderer_id="powerpoint",
                                                     output_format="pptx", output_name="conference.pptx")
        self.assertEqual(result["path"], "builds/presentations/conference.pptx")

    def test_failed_quarto_does_not_overwrite_existing_artifact(self):
        destination = self.root / "builds/presentations/talk.html"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"last good export")
        self.engine.create_file(self.project, "talk.slides.md", "# failed")
        def partial_failure(args, **kwargs):
            candidate = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
            candidate.write_bytes(b"partial, invalid HTML")
            return subprocess.CompletedProcess(args, 3, stdout="", stderr="local render failed")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=partial_failure):
            with self.assertRaisesRegex(PresentationError, "local render failed"):
                self.engine.export_presentation(self.project, "talk.slides.md", renderer_id="reveal", output_format="html")
        self.assertEqual(destination.read_bytes(), b"last good export")
        self.assertEqual(sorted(x.name for x in destination.parent.iterdir()), ["talk.html"])
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=self._quarto_simulator):
            self.engine.export_presentation(self.project, "talk.slides.md", renderer_id="reveal", output_format="html")
        self.assertNotEqual(destination.read_bytes(), b"last good export")

    def test_rejects_symlinked_build_path_even_if_inside_project(self):
        (self.root / "staged").mkdir()
        (self.root / "builds").symlink_to(self.root / "staged", target_is_directory=True)
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"):
            with self.assertRaisesRegex(PresentationError, "symlink"):
                self.engine.export_presentation(self.project, "paper/talk.slides.md", renderer_id="reveal", output_format="html")
        self.assertEqual(list((self.root / "staged").iterdir()), [])

    def test_pinned_style_bundle_portability_and_profile(self):
        theme_root = self.base / "theme"
        theme_root.mkdir()
        (theme_root / "beamerthemeMinimal.sty").write_text("\\ProvidesPackage{beamerthemeMinimal}\n", encoding="utf-8")
        metadata = self.engine.import_beamer_style(theme_root, version="1.0.0")
        ref = StyleReference(metadata["identifier"], metadata["version"], "beamer")
        family = self.engine.create_presentation_style_family(identifier="research", version="1.0", label="Research",
             variants={"beamer":ref})
        self.assertEqual(family["identifier"], "research")
        profile = self.engine.save_presentation_profile(self.project, "paper/talk.slides.md",
                                                       renderer_id="beamer", output_format="pdf", style=ref)
        self.assertEqual(profile["style"]["identifier"], ref.identifier)
        package = self.engine.export_presentation_style_bundle(self.base / "style.zip", family_id="research", family_version="1.0")
        restored = DocumentEngine(self.base / "other-workbench")
        self.addCleanup(restored.notebooks.shutdown_all)
        result = restored.import_presentation_style_bundle(package)
        self.assertEqual(result["installed_versions"], 1)
        self.assertEqual(restored.presentation_style_family_catalog()[0], family)
        self.assertEqual(restored.presentation_styles.resolve(ref).manifest.as_dict(), metadata)
        self.assertEqual(self.engine.presentation_profile(self.project, "paper/talk.slides.md"), profile)

    @unittest.skipUnless(shutil.which("latexmk"), "latexmk not installed locally")
    def test_real_native_beamer_render_with_nested_theme_and_unchanged_source(self):
        directory = self.root / "beamer"
        (directory / "themes").mkdir(parents=True)
        self.engine.create_file(self.project, "beamer/themes/beamerthemeLocal.sty",
                                "\\ProvidesPackage{beamerthemeLocal}\n\\setbeamertemplate{navigation symbols}{}\n")
        main = "\\documentclass{beamer}\n\\usetheme{Local}\n\\begin{document}\n\\begin{frame}{Real local PDF}Hello\\end{frame}\n\\end{document}\n"
        self.engine.create_file(self.project, "beamer/main.tex", main)
        source = self.root / "beamer/main.tex"
        before = source.read_bytes()
        self.assertIn("beamer/main.tex", self.engine.native_beamer_entrypoints(self.project))
        result = self.engine.export_presentation(self.project, "beamer/main.tex", renderer_id="beamer", output_format="pdf")
        self.assertTrue((self.root / result["path"]).read_bytes().startswith(b"%PDF"))
        self.assertEqual(source.read_bytes(), before)


@unittest.skipUnless(importlib.util.find_spec("flask") is not None, "Flask not installed locally")
class PresentationFinalHttpIntegrationTests(unittest.TestCase):
    def setUp(self):
        import importlib
        web = importlib.import_module("tech_documents.web.app")
        self.web = web
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original = web.engine
        web.engine = DocumentEngine(self.temp.name)
        self.addCleanup(setattr, web, "engine", self.original)
        self.addCleanup(web.engine.notebooks.shutdown_all)
        self.project = web.engine.create_project("test")
        web.engine.create_file(self.project, "slides.md", "# Offline")
        self.client = web.app.test_client()

    def test_export_catalog_conversion_and_retrieval(self):
        path = f"/api/presentations/{self.project}/slides.md/exports"
        catalog = self.client.get(path)
        self.assertEqual(catalog.status_code, 200)
        self.assertIn("conversion:notebook", {row["id"] for row in catalog.get_json()["outputs"]})
        result = self.client.post(path, json={"conversion_target":"notebook"})
        self.assertEqual(result.status_code, 200, result.get_json())
        self.assertEqual(self.client.get(result.get_json()["download_url"]).status_code, 200)


if __name__ == "__main__":
    unittest.main()
