"""PS-04: safe local Beamer project discovery and reusable style installation."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from tech_documents import DocumentEngine
from tech_documents.presentations import (
    PresentationError, PresentationStyleRegistry, StyleManifest,
    import_beamer_style, inspect_beamer_source,
)


class BeamerImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "csci447"
        self.theme_dir = self.project / "theory_week" / "beamerthemeNISL_MSU"
        self.theme_dir.mkdir(parents=True)
        (self.project / "theory.tex").write_text(
            r"\documentclass[aspectratio=169]{beamer}" + "\n" + r"\usetheme{MSU}" + "\n" + r"\begin{document}" + "\n", encoding="utf-8",
        )
        (self.project / "theory_week" / "theory.tex").write_text(
            r"\documentclass{beamer}" + "\n" + r"\usetheme{MSU}" + "\n", encoding="utf-8",
        )
        (self.theme_dir / "beamerthemeMSU.sty").write_text(
            r"\RequirePackage{tikz}" + "\n"
            + r"\usepackage{beamercolorthemeMSU}" + "\n"
            + r"\includegraphics{MSUlogoV.png}" + "\n", encoding="utf-8",
        )
        (self.theme_dir / "beamercolorthemeMSU.sty").write_text("% MSU colors\n", encoding="utf-8")
        (self.theme_dir / "MSUlogoV.png").write_bytes(b"PNG-TEST")
        (self.project / "Makefile").write_text("all:\n\trm -rf ~/never-execute\n", encoding="utf-8")
        (self.project / "unrelated.pdf").write_bytes(b"unrelated")
        self.registry = PresentationStyleRegistry(self.base / "registry")

    def test_folder_inspection_recognizes_theme_and_project_entrypoints(self):
        inspection = inspect_beamer_source(self.project)
        self.assertEqual(inspection.source_name, "csci447")
        self.assertEqual(inspection.project_entrypoints, ("theory.tex", "theory_week/theory.tex"))
        self.assertEqual(len(inspection.themes), 1)
        candidate = inspection.themes[0]
        self.assertEqual(candidate.theme_name, "MSU")
        self.assertEqual(candidate.selector, "theory_week/beamerthemeNISL_MSU/beamerthemeMSU.sty")
        self.assertEqual(candidate.project_entrypoints, inspection.project_entrypoints)
        self.assertEqual(candidate.external_packages, ("tikz",))
        self.assertEqual(candidate.warnings, ())
        self.assertEqual(candidate.asset_paths, (
            "MSUlogoV.png", "beamercolorthemeMSU.sty", "beamerthemeMSU.sty",
        ))

    def test_folder_registration_is_version_pinned_and_content_independent(self):
        manifest = import_beamer_style(self.registry, self.project, version="1.0.0")
        self.assertEqual(manifest.kind, "beamer")
        self.assertEqual(manifest.entrypoint, "beamerthemeMSU.sty")
        self.assertEqual(manifest.renderer_ids, ("beamer",))
        self.assertEqual(manifest.identifier, "beamer.msu")
        self.assertEqual(StyleManifest.from_dict(manifest.as_dict()), manifest)
        installed = self.registry.resolve(manifest.reference, renderer_id="beamer")
        self.assertEqual(installed.asset("MSUlogoV.png").read_bytes(), b"PNG-TEST")
        self.assertFalse((installed.assets_dir / "Makefile").exists())
        self.assertFalse((installed.assets_dir / "theory.tex").exists())
        self.assertFalse((installed.assets_dir / "unrelated.pdf").exists())
        self.assertEqual([m.reference for m in self.registry.list_styles()], [manifest.reference])
        with self.assertRaisesRegex(PresentationError, "already installed"):
            import_beamer_style(self.registry, self.project, version="1.0.0")
        self.assertEqual((self.project / "theory.tex").read_text(encoding="utf-8").splitlines()[0],
                         r"\documentclass[aspectratio=169]{beamer}")

    def test_zip_inspection_import_and_engine_facade(self):
        archive_path = self.base / "csci447.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in self.project.rglob("*"):
                if path.is_file():
                    archive.write(path, arcname="csci447/" + path.relative_to(self.project).as_posix())
        engine = DocumentEngine(self.base / "workbench")
        details = engine.inspect_beamer_styles(archive_path)
        self.assertEqual(len(details["themes"]), 1)
        self.assertEqual(details["themes"][0]["theme_name"], "MSU")
        self.assertEqual(details["themes"][0]["selector"],
                         "csci447/theory_week/beamerthemeNISL_MSU/beamerthemeMSU.sty")
        manifest = engine.import_beamer_style(archive_path, version="2026.1")
        self.assertEqual(manifest["entrypoint"], "beamerthemeMSU.sty")
        self.assertEqual(len(engine.presentation_style_catalog(kind="beamer")), 1)
        local = import_beamer_style(self.registry, archive_path, version="1.0.0")
        installed = self.registry.resolve(local.reference)
        self.assertEqual(installed.asset("MSUlogoV.png").read_bytes(), b"PNG-TEST")

    def test_ambiguous_themes_require_selection(self):
        (self.theme_dir / "beamerthemeOther.sty").write_text("% Another theme\n", encoding="utf-8")
        inspection = inspect_beamer_source(self.project)
        self.assertEqual(len(inspection.themes), 2)
        with self.assertRaisesRegex(PresentationError, "Select a Beamer theme"):
            import_beamer_style(self.registry, self.project, version="1.0")
        manifest = import_beamer_style(
            self.registry, self.project, version="1.0",
            selector=next(theme.selector for theme in inspection.themes if theme.theme_name == "MSU"),
        )
        self.assertEqual(manifest.entrypoint, "beamerthemeMSU.sty")
        with self.assertRaisesRegex(PresentationError, "selector was not found"):
            import_beamer_style(self.registry, self.project, version="1.1", selector="no-such-theme")

    def test_project_with_only_builtin_theme_is_inspectable_not_installable(self):
        (self.theme_dir / "beamerthemeMSU.sty").unlink()
        result = inspect_beamer_source(self.project)
        self.assertEqual(result.project_entrypoints, ("theory.tex", "theory_week/theory.tex"))
        self.assertEqual(result.themes, ())
        self.assertTrue(result.warnings)
        with self.assertRaisesRegex(PresentationError, "Select a Beamer theme"):
            import_beamer_style(self.registry, self.project, version="1.0")
        self.assertEqual(self.registry.list_styles(), [])

    def test_missing_theme_images_reported_without_claiming_compile(self):
        (self.theme_dir / "MSUlogoV.png").unlink()
        candidate = inspect_beamer_source(self.project).themes[0]
        self.assertTrue(any("Unresolved theme image" in item for item in candidate.warnings))
        self.assertEqual(candidate.external_packages, ("tikz",))

    def test_symlink_directory_and_assets_rejected(self):
        outside = self.base / "outside.sty"
        outside.write_text("outside", encoding="utf-8")
        (self.theme_dir / "linked.sty").symlink_to(outside)
        with self.assertRaisesRegex(PresentationError, "symlinks"):
            inspect_beamer_source(self.project)
        (self.theme_dir / "linked.sty").unlink()
        linked = self.base / "linked"
        linked.symlink_to(self.project, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "normal"):
            inspect_beamer_source(linked)

    def test_malicious_zip_entries_rejected_before_install(self):
        for bad_name in ("../escape.sty", "/etc/passwd", "C:/evil.sty", "dir\\malicious.sty"):
            with self.subTest(name=bad_name):
                target = self.base / "evil.zip"
                with zipfile.ZipFile(target, "w") as archive:
                    archive.writestr("beamerthemeSafe.sty", "% safe")
                    archive.writestr(bad_name, "bad")
                with self.assertRaisesRegex(PresentationError, "unsafe entry path"):
                    import_beamer_style(self.registry, target, version="1.0")
        self.assertEqual(self.registry.list_styles(), [])

    def test_zip_symlink_and_duplicate_rejected(self):
        target = self.base / "evil.zip"
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("beamerthemeSafe.sty", "% safe")
            info = zipfile.ZipInfo("linked.sty")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, "../private")
        with self.assertRaisesRegex(PresentationError, "symlink"):
            inspect_beamer_source(target)
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("beamerthemeSafe.sty", "% safe")
            archive.writestr("beamerthemeSAFE.sty", "% other")
        with self.assertRaisesRegex(PresentationError, "duplicate"):
            inspect_beamer_source(target)

    def test_standalone_theme_directory_and_zip(self):
        folder_inspection = inspect_beamer_source(self.theme_dir)
        self.assertEqual(len(folder_inspection.themes), 1)
        self.assertEqual(folder_inspection.themes[0].selector, "beamerthemeMSU.sty")
        manifest = import_beamer_style(self.registry, self.theme_dir, version="2", label="My Theme")
        self.assertEqual(manifest.entrypoint, "beamerthemeMSU.sty")
        self.assertEqual(manifest.label, "My Theme")
        archive_path = self.base / "standalone.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for path in self.theme_dir.iterdir():
                archive.write(path, arcname=path.name)
        imported = import_beamer_style(self.registry, archive_path, version="3")
        self.assertEqual(imported.entrypoint, "beamerthemeMSU.sty")
        self.assertEqual(len(imported.assets), 3)

    def test_entrypoint_is_validated_by_registry(self):
        with self.assertRaisesRegex(ValueError, "entrypoint"):
            self.registry.install(
                identifier="bad", version="1", kind="beamer", label="Bad", renderer_ids=("beamer",),
                source_dir=self.theme_dir, asset_paths=("beamerthemeMSU.sty",),
                entrypoint="absent.sty",
            )
        self.assertEqual(self.registry.list_styles(), [])

    def test_malformed_zip_is_reported(self):
        target = self.base / "not-a-zip.zip"
        target.write_text("not really a zip", encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "Cannot read"):
            inspect_beamer_source(target)

    def test_legacy_registry_manifests_remain_readable(self):
        original = self.registry.install(
            identifier="legacy", version="1", kind="beamer", label="Legacy",
            renderer_ids=("beamer",),
        )
        self.assertNotIn("entrypoint", original.as_dict())
        self.assertEqual(self.registry.resolve(original.reference).manifest, original)
        self.assertEqual(StyleManifest.from_dict(original.as_dict()), original)


if __name__ == "__main__":
    unittest.main()
