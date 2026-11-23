"""PS-03: local, immutable, renderer-neutral presentation style packages."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tech_documents import DocumentEngine
from tech_documents.presentations import (
    PresentationError,
    PresentationExportRequest,
    PresentationExportResult,
    PresentationService,
    PresentationStyleRegistry,
    RendererCapabilities,
    StyleManifest,
    StyleReference,
)


class StyleRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.registry_root = self.base / "registry"
        self.registry = PresentationStyleRegistry(self.registry_root)
        self.sources = self.base / "source"
        (self.sources / "theme" / "pictures").mkdir(parents=True)
        (self.sources / "theme" / "beamerthemeMSU.sty").write_text("% MSU theme\n", encoding="utf-8")
        (self.sources / "theme" / "pictures" / "logo.png").write_bytes(b"\x89PNG\r\nTEST")

    def install(self, **kwargs) -> StyleManifest:
        options = dict(
            identifier="msu.nisl", version="1.0.0", kind="beamer",
            label="MSU NISL", renderer_ids=("beamer",),
            source_dir=self.sources, asset_paths=(
                "theme/beamerthemeMSU.sty", "theme/pictures/logo.png",
            ), description="MSU presentation styling", source_name="local test project",
        )
        options.update(kwargs)
        return self.registry.install(**options)

    def test_install_discover_resolve_assets_persistence_and_filtering(self):
        self.assertEqual(self.registry.list_styles(), [])
        manifest = self.install()
        self.assertEqual(manifest.identifier, "msu.nisl")
        self.assertEqual(manifest.renderer_ids, ("beamer",))
        self.assertEqual(len(manifest.assets), 2)
        self.assertTrue(all(len(asset.sha256) == 64 for asset in manifest.assets))
        registry_again = PresentationStyleRegistry(self.registry_root)
        self.assertEqual(registry_again.list_styles(), [manifest])
        self.assertEqual(registry_again.list_styles(kind="beamer", renderer_id="beamer"), [manifest])
        self.assertEqual(registry_again.list_styles(kind="reveal"), [])
        self.assertEqual(registry_again.list_styles(renderer_id="powerpoint"), [])
        package = registry_again.resolve(manifest.reference, renderer_id="beamer")
        self.assertEqual(package.manifest, manifest)
        self.assertEqual(package.asset("theme/pictures/logo.png").read_bytes(), b"\x89PNG\r\nTEST")
        with self.assertRaisesRegex(PresentationError, "not declared"):
            package.asset("unlisted.txt")
        self.assertFalse((self.sources / "theme" / "beamerthemeMSU.sty").samefile(
            package.asset("theme/beamerthemeMSU.sty")))
        self.assertEqual(StyleManifest.from_dict(manifest.as_dict()), manifest)
        with self.assertRaisesRegex(PresentationError, "not compatible"):
            registry_again.resolve(manifest.reference, renderer_id="reveal")

    def test_pinned_versions_are_immutable_and_uninstall_is_narrow(self):
        first = self.install()
        with self.assertRaisesRegex(PresentationError, "already installed"):
            self.install()
        self.assertEqual(len(self.registry.list_styles()), 1)
        second = self.install(version="1.1.0", label="MSU update")
        self.assertEqual(len(self.registry.list_styles()), 2)
        self.registry.uninstall(first.reference)
        self.assertEqual(self.registry.list_styles(), [second])
        with self.assertRaisesRegex(PresentationError, "not installed"):
            self.registry.resolve(first.reference)
        self.registry.resolve(second.reference)

    def test_detects_tampering_and_corrupt_manifest(self):
        manifest = self.install()
        installed = self.registry.resolve(manifest.reference)
        installed.asset("theme/beamerthemeMSU.sty").write_text("malicious change", encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "integrity verification"):
            self.registry.resolve(manifest.reference)
        # Discovery lists metadata without hashing every asset.
        self.assertEqual(self.registry.list_styles(), [manifest])
        manifest_file = installed.package_dir / "manifest.json"
        bad = json.loads(manifest_file.read_text(encoding="utf-8"))
        bad["assets"][0]["path"] = "../../outside.txt"
        manifest_file.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "Invalid presentation style manifest"):
            self.registry.resolve(manifest.reference)
        with self.assertRaisesRegex(PresentationError, "Corrupt registered style"):
            self.registry.list_styles()

    def test_missing_asset_rolls_back_without_publishing_partial_package(self):
        with self.assertRaisesRegex(PresentationError, "does not exist"):
            self.install(asset_paths=("theme/beamerthemeMSU.sty", "missing.sty"))
        self.assertEqual(self.registry.list_styles(), [])
        self.assertEqual(list(self.registry_root.glob(".style-install-*")), [])
        self.install()  # A failed install does not reserve the version.

    def test_path_traversal_absolute_and_windows_asset_paths_are_rejected(self):
        for invalid in ("../outside", "x/../y", "./theme/x", "/etc/passwd", "C:/secret", "x\\y", "a//b"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.install(asset_paths=(invalid,))
        self.assertFalse((self.registry_root / "styles").exists())
        for invalid in ("..", "../x", "a/b", ""):
            with self.subTest(version=invalid), self.assertRaises(ValueError):
                self.install(version=invalid)

    def test_symlink_asset_and_symlink_install_root_are_rejected(self):
        outside = self.base / "outside.sty"
        outside.write_text("private", encoding="utf-8")
        (self.sources / "linked.sty").symlink_to(outside)
        with self.assertRaisesRegex(PresentationError, "symlinks"):
            self.install(asset_paths=("linked.sty",))
        linked_root = self.base / "linked-root"
        linked_root.symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "symlink"):
            PresentationStyleRegistry(linked_root).install(
                identifier="test", version="1", kind="beamer", label="Test", renderer_ids=("beamer",),
            )

    def test_symlinked_registry_kind_cannot_redirect_directory_creation(self):
        external = self.base / "external"
        external.mkdir()
        (self.registry_root / "styles").mkdir(parents=True)
        (self.registry_root / "styles" / "beamer").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "symlinks"):
            self.install()
        self.assertEqual(list(external.iterdir()), [])

    def test_duplicate_assets_and_invalid_manifest_are_rejected(self):
        with self.assertRaises(ValueError):
            self.install(asset_paths=("theme/beamerthemeMSU.sty", "theme/beamerthemeMSU.sty"))
        with self.assertRaises(ValueError):
            self.install(renderer_ids=())
        with self.assertRaises(ValueError):
            self.install(renderer_ids=("beamer", "beamer"))
        with self.assertRaises(ValueError):
            self.install(label="")
        with self.assertRaises(ValueError):
            self.install(identifier="..")
        self.assertEqual(self.registry.list_styles(), [])

    def test_asset_free_style_and_engine_integration(self):
        engine = DocumentEngine(self.base / "workbench")
        self.assertEqual(engine.presentation_style_catalog(), [])
        empty = engine.presentation_styles.install(
            identifier="standard", version="2026.1", kind="beamer", label="Default Beamer",
            renderer_ids=("beamer",),
        )
        self.assertEqual(engine.presentation_style_catalog(renderer_id="beamer"), [empty.as_dict()])
        self.assertEqual(engine.presentation_style_catalog(renderer_id="reveal"), [])
        self.assertIs(engine.presentations.styles, engine.presentation_styles)
        # PS-11 wires all three built-in presentation renderers to the registry.
        caps = {cap["id"]: cap for cap in engine.presentation_renderer_capabilities()}
        self.assertEqual(caps["beamer"]["style_kinds"], ["beamer"])
        self.assertEqual(caps["reveal"]["style_kinds"], ["reveal"])
        self.assertEqual(caps["powerpoint"]["style_kinds"], ["powerpoint"])


class StyleResolutionInServiceTests(unittest.TestCase):
    def test_service_preflights_pinned_registry_styles_for_compatible_renderers(self):
        class FakeStyledRenderer:
            renderer_id = "beamer"

            def capabilities(self):
                return RendererCapabilities(
                    "beamer", "fake", ("markdown",), ("pdf",), ("beamer",), True, "",
                )

            def render(self, request):
                output = request.project_root / "slides.pdf"
                output.write_bytes(b"PDF")
                return PresentationExportResult("beamer", "pdf", output)

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base / "project"
            project.mkdir()
            source = project / "deck.md"
            source.write_text("# Test", encoding="utf-8")
            registry = PresentationStyleRegistry(base / "styles")
            service = PresentationService([FakeStyledRenderer()], styles=registry)
            request = PresentationExportRequest(
                source_path=source, project_root=project, source_kind="markdown",
                renderer_id="beamer", output_format="pdf",
                style=StyleReference("msu", "1", "beamer"),
            )
            with self.assertRaisesRegex(PresentationError, "not installed"):
                service.export(request)
            registry.install(identifier="msu", version="1", kind="beamer", label="MSU", renderer_ids=("reveal",))
            with self.assertRaisesRegex(PresentationError, "not compatible"):
                service.export(request)
            registry.install(identifier="msu", version="2", kind="beamer", label="MSU", renderer_ids=("beamer",))
            request = PresentationExportRequest(
                source_path=source, project_root=project, source_kind="markdown",
                renderer_id="beamer", output_format="pdf",
                style=StyleReference("msu", "2", "beamer"),
            )
            self.assertTrue(service.export(request).output_path.is_file())
            self.assertEqual(source.read_text(encoding="utf-8"), "# Test")


if __name__ == "__main__":
    unittest.main()
