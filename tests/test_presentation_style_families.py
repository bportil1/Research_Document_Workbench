"""PS-12: immutable multi-renderer families and portable offline ZIP packages."""
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tech_documents.api import DocumentEngine
from tech_documents.presentations import (
    BrandingTokens, PresentationError, PresentationStyleFamilyRegistry,
    PresentationStyleRegistry, StyleFamilyManifest, StyleReference,
    export_style_bundle, import_style_bundle,
)


class PresentationStyleFamilyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "registry"
        self.styles = PresentationStyleRegistry(self.root)
        self.families = PresentationStyleFamilyRegistry(self.styles)
        source = self.base / "source"
        source.mkdir()
        (source / "beamerthemeExample.sty").write_text("% trusted theme\n", encoding="utf-8")
        (source / "theme.css").write_text(".reveal { color: #123456; }\n", encoding="utf-8")
        self.beamer = self.styles.install(identifier="example.msu", version="1.0", kind="beamer",
                                          label="Example Beamer", renderer_ids=("beamer",),
                                          source_dir=source, asset_paths=["beamerthemeExample.sty"],
                                          entrypoint="beamerthemeExample.sty")
        self.reveal = self.styles.install(identifier="example.web", version="2.0", kind="reveal",
                                          label="Reveal CSS", renderer_ids=("reveal",),
                                          source_dir=source, asset_paths=["theme.css"], entrypoint="theme.css")
        self.powerpoint = self.styles.install(identifier="example.ppt", version="1", kind="powerpoint",
                                              label="PowerPoint empty", renderer_ids=("powerpoint",))

    def make_family(self, **kwargs):
        params = dict(identifier="lab.theme", version="2026.1", label="Research Lab",
                      description="Cross-renderer family", variants={
                          "beamer": self.beamer.reference, "reveal": self.reveal.reference,
                          "powerpoint": self.powerpoint.reference,
                      }, branding=BrandingTokens(colors={"primary": "#004477", "accent": "#F1B233"},
                                               fonts={"heading": "Source Sans Pro"}),
                      overrides={"reveal": BrandingTokens(colors={"background": "#FFFFFF"})})
        params.update(kwargs)
        return self.families.create(**params)

    def test_family_creation_persistence_version_pin_filters_and_renderer_overrides(self):
        family = self.make_family()
        self.assertEqual(len(family.variants), 3)
        self.assertEqual(family.branding.colors["primary"], "#004477")
        self.assertEqual(family.variants[2].renderer_id, "reveal")
        self.assertEqual(family.variants[2].branding.colors["background"], "#FFFFFF")
        other = PresentationStyleFamilyRegistry(PresentationStyleRegistry(self.root))
        self.assertEqual(other.resolve("lab.theme", "2026.1"), family)
        self.assertEqual(other.list_families(renderer_id="reveal"), [family])
        self.assertEqual(other.list_families(renderer_id="other"), [])
        self.assertEqual(StyleFamilyManifest.from_dict(family.as_dict()), family)
        with self.assertRaisesRegex(PresentationError, "already exists"):
            self.make_family()
        other.uninstall(family.identifier, family.version)
        self.assertEqual(other.list_families(), [])
        self.styles.resolve(self.beamer.reference)  # Removing a family does not remove a style.

    def test_validation_rejects_invalid_brand_tokens_variants_and_missing_logos(self):
        with self.assertRaises(ValueError):
            BrandingTokens(colors={"primary": "red"})
        with self.assertRaises(ValueError):
            BrandingTokens(colors={"highlight": "#000000"})
        with self.assertRaises(ValueError):
            BrandingTokens(fonts={"body": "\n"})
        with self.assertRaisesRegex(ValueError, "override"):
            self.make_family(overrides={"unknown": BrandingTokens()})
        with self.assertRaisesRegex(PresentationError, "not compatible"):
            self.make_family(variants={"powerpoint": self.beamer.reference}, overrides={})
        with self.assertRaisesRegex(PresentationError, "logo"):
            self.make_family(logos={"beamer": "secret.png"})
        self.assertEqual(self.families.list_families(), [])

    def test_detects_asset_tampering_and_family_manifest_tampering(self):
        family = self.make_family()
        asset = self.styles.resolve(self.reveal.reference).asset("theme.css")
        asset.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "integrity"):
            self.families.resolve(family.identifier, family.version)
        asset.write_text(".reveal { color: #123456; }\n", encoding="utf-8")
        path = self.families._path(family.identifier, family.version)
        payload = json.loads(path.read_text())
        payload["variants"][0]["style"]["identifier"] = "not-installed"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "not installed"):
            self.families.resolve(family.identifier, family.version)

    def test_symlinked_family_storage_and_invalid_metadata_rejected(self):
        external = self.base / "external"
        external.mkdir()
        (self.root / "families").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.make_family()
        self.assertEqual(list(external.iterdir()), [])
        with self.assertRaises(ValueError):
            self.make_family(identifier="../bad")

    def test_family_bundle_roundtrip_across_independent_registries(self):
        family = self.make_family()
        exported = export_style_bundle(self.styles, (v.style for v in family.variants),
                                       self.base / "portable.zip", family=family)
        second_styles = PresentationStyleRegistry(self.base / "other")
        second_families = PresentationStyleFamilyRegistry(second_styles)
        result = import_style_bundle(second_styles, second_families, exported)
        self.assertEqual(result["installed_versions"], 3)
        self.assertEqual(len(result["styles"]), 3)
        self.assertEqual(second_families.resolve(family.identifier, family.version), family)
        for variant in family.variants:
            self.assertEqual(second_styles.resolve(variant.style).manifest,
                             self.styles.resolve(variant.style).manifest)
        with self.assertRaisesRegex(PresentationError, "already installed"):
            import_style_bundle(second_styles, second_families, exported)
        self.assertEqual(exported.read_bytes(), export_style_bundle(self.styles,
            (v.style for v in family.variants), self.base / "portable-again.zip", family=family).read_bytes())

    def test_standalone_style_bundle_and_reusing_identical_style_versions(self):
        exported = export_style_bundle(self.styles, [self.beamer.reference], self.base / "single.zip")
        target_styles = PresentationStyleRegistry(self.base / "target")
        target_families = PresentationStyleFamilyRegistry(target_styles)
        result = import_style_bundle(target_styles, target_families, exported)
        self.assertIsNone(result["family"])
        self.assertEqual(result["installed_versions"], 1)
        # Second import reuses the exact same immutable assets.
        result = import_style_bundle(target_styles, target_families, exported)
        self.assertEqual(result["installed_versions"], 0)

    def test_bundle_tampering_undeclared_files_duplicate_paths_and_hashes(self):
        family = self.make_family()
        exported = export_style_bundle(self.styles, (v.style for v in family.variants),
                                       self.base / "portable.zip", family=family)
        with zipfile.ZipFile(exported) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        asset_key = next(key for key in contents if key.endswith(".sty"))
        for variant, changes in {
            "hash": {asset_key: b"mismatched"},
            "extra": {"unexpected.txt": b"no"},
            "manifest": {"bundle.json": b'{"schema_version":999}'},
        }.items():
            target = self.base / (variant + ".zip")
            with zipfile.ZipFile(target, "w") as archive:
                for key, value in {**contents, **changes}.items():
                    archive.writestr(key, value)
            registry = PresentationStyleRegistry(self.base / ("import-" + variant))
            with self.assertRaises(PresentationError, msg=variant):
                import_style_bundle(registry, PresentationStyleFamilyRegistry(registry), target)
            self.assertEqual(registry.list_styles(), [])
        duplicate = self.base / "duplicate.zip"
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("bundle.json", contents["bundle.json"])
            archive.writestr("bundle.json", contents["bundle.json"])
        registry = PresentationStyleRegistry(self.base / "duplicates")
        with self.assertRaisesRegex(PresentationError, "duplicate"):
            import_style_bundle(registry, PresentationStyleFamilyRegistry(registry), duplicate)

    def test_conflicting_version_does_not_overwrite_and_partial_install_rollback(self):
        family = self.make_family()
        archive = export_style_bundle(self.styles, (v.style for v in family.variants),
                                      self.base / "family.zip", family=family)
        target_styles = PresentationStyleRegistry(self.base / "conflict")
        target_families = PresentationStyleFamilyRegistry(target_styles)
        target_styles.install(identifier=self.beamer.identifier, version=self.beamer.version,
                              kind=self.beamer.kind, label="different", renderer_ids=("beamer",))
        with self.assertRaisesRegex(PresentationError, "differs"):
            import_style_bundle(target_styles, target_families, archive)
        self.assertEqual(len(target_styles.list_styles()), 1)
        self.assertEqual(target_families.list_families(), [])

        # Fake failure on late family commit -> new styles must be rolled back.
        target_styles = PresentationStyleRegistry(self.base / "rollback")
        target_families = PresentationStyleFamilyRegistry(target_styles)
        def bad_install(_manifest):
            raise PresentationError("late family error")
        target_families.install = bad_install
        with self.assertRaisesRegex(PresentationError, "late family error"):
            import_style_bundle(target_styles, target_families, archive)
        self.assertEqual(target_styles.list_styles(), [])

    def test_import_revalidates_portable_css_and_pptx_assets(self):
        # Direct registry callers can install arbitrary files; a portable import
        # must not bypass the CSS/PPTX checks used by the PS-11 UI importer.
        source = self.base / "unsafe"
        source.mkdir()
        (source / "remote.css").write_text('@import url("https://example.com/a.css");', encoding="utf-8")
        bad_css = self.styles.install(
            identifier="unsafe-css", version="1", kind="reveal", label="unsafe",
            renderer_ids=("reveal",), source_dir=source, asset_paths=("remote.css",),
            entrypoint="remote.css",
        )
        archive = export_style_bundle(self.styles, [bad_css.reference], self.base / "unsafe.zip")
        fresh = PresentationStyleRegistry(self.base / "fresh")
        with self.assertRaisesRegex(PresentationError, "@import"):
            import_style_bundle(fresh, PresentationStyleFamilyRegistry(fresh), archive)
        self.assertEqual(fresh.list_styles(), [])

        (source / "bad.pptx").write_bytes(b"not a PowerPoint template")
        bad_pptx = self.styles.install(
            identifier="unsafe-ppt", version="1", kind="powerpoint", label="unsafe",
            renderer_ids=("powerpoint",), source_dir=source, asset_paths=("bad.pptx",),
            entrypoint="bad.pptx",
        )
        archive = export_style_bundle(self.styles, [bad_pptx.reference], self.base / "unsafe-ppt.zip")
        with self.assertRaisesRegex(PresentationError, "valid PowerPoint"):
            import_style_bundle(fresh, PresentationStyleFamilyRegistry(fresh), archive)
        self.assertEqual(fresh.list_styles(), [])

    def test_family_dependency_prevents_accidental_style_uninstall(self):
        self.make_family()
        engine = DocumentEngine(self.base / "workbench-guard")
        engine.presentation_styles = self.styles
        engine.presentation_style_families = self.families
        with self.assertRaisesRegex(PresentationError, "remove that family first"):
            engine.uninstall_presentation_style(self.beamer.reference)
        self.styles.resolve(self.beamer.reference)

    def test_workbench_engine_exposes_family_and_portability_without_ui(self):
        engine = DocumentEngine(self.base / "workbench")
        a = engine.presentation_styles.install(identifier="generic", version="1", kind="beamer",
                                               label="Generic", renderer_ids=("beamer",))
        family = engine.create_presentation_style_family(identifier="general", version="1", label="General",
                                                         variants={"beamer": a.reference})
        self.assertEqual(engine.presentation_style_family_catalog(), [family])
        bundle = engine.export_presentation_style_bundle(self.base / "engine.zip", family_id="general", family_version="1")
        self.assertTrue(bundle.is_file())
        other = DocumentEngine(self.base / "workbench2")
        result = other.import_presentation_style_bundle(bundle)
        self.assertEqual(result["family"], family)


if __name__ == "__main__":
    unittest.main()
