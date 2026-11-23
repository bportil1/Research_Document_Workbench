"""PS-06: local version-pinned, per-presentation build configuration tests."""
from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tech_documents.api import DocumentEngine
from tech_documents.presentations import (
    PresentationBuildProfile, PresentationError, PresentationProfileStore,
    StyleReference,
)


class PresentationProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "workspace"
        self.engine = DocumentEngine(self.base)
        self.addCleanup(self.engine.notebooks.shutdown_all)
        self.a = self.engine.create_project("one")
        self.b = self.engine.create_project("two")
        self.engine.create_file(self.a, "talk.slides.md", "# One")
        self.engine.create_file(self.b, "talk.slides.md", "# Two")
        self.src_a = self.engine.item_path(self.a, "talk.slides.md")
        self.src_b = self.engine.item_path(self.b, "talk.slides.md")

    def register_style(self, version="1.0.0"):
        theme = self.base / f"theme{version}"
        theme.mkdir()
        (theme / "beamerthemeMSU.sty").write_text("% custom", encoding="utf-8")
        self.engine.presentation_styles.install(
            identifier="msu", version=version, kind="beamer", label="MSU",
            renderer_ids=("beamer",), source_dir=theme,
            asset_paths=("beamerthemeMSU.sty",), entrypoint="beamerthemeMSU.sty",
        )
        return StyleReference("msu", version, "beamer")

    def test_per_source_profiles_are_independent_even_with_same_filename(self):
        one = self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="beamer", output_format="pdf")
        two = self.engine.save_presentation_profile(self.b, "talk.slides.md", renderer_id="reveal", output_format="html")
        self.assertEqual(one["renderer_id"], "beamer")
        self.assertEqual(two["renderer_id"], "reveal")
        self.assertEqual(self.engine.presentation_profile(self.a, "talk.slides.md"), one)
        self.assertEqual(self.engine.presentation_profile(self.b, "talk.slides.md"), two)
        (self.engine.project_path(self.a) / "nested").mkdir()
        self.engine.create_file(self.a, "nested/talk.slides.md", "# Nested")
        self.assertIsNone(self.engine.presentation_profile(self.a, "nested/talk.slides.md"))
        self.assertEqual(self.src_a.read_text(encoding="utf-8"), "# One")
        self.assertEqual(self.src_b.read_text(encoding="utf-8"), "# Two")

    def test_persistence_after_engine_restart_without_cross_project_leakage(self):
        ref = self.register_style()
        saved = self.engine.save_presentation_profile(
            self.a, "talk.slides.md", renderer_id="beamer", output_format="pdf",
            output_name="conference.pdf", style=ref,
        )
        self.assertRegex(saved["style_manifest_sha256"], r"^[0-9a-f]{64}$")
        newer = DocumentEngine(self.base)
        self.addCleanup(newer.notebooks.shutdown_all)
        self.assertEqual(newer.presentation_profile(self.a, "talk.slides.md"), saved)
        self.assertIsNone(newer.presentation_profile(self.b, "talk.slides.md"))
        self.assertFalse((Path(self.src_a).parent / ".workbench-presentation-configs").exists())
        self.assertTrue((self.base / ".workbench-presentation-configs" / "profiles").exists())

    def test_installed_style_version_is_pinned(self):
        first = self.register_style("1.0.0")
        saved = self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="beamer", output_format="pdf", style=first)
        self.register_style("2.0.0")
        self.assertEqual(self.engine.presentation_profile(self.a, "talk.slides.md"), saved)
        self.assertEqual(saved["style"]["version"], "1.0.0")
        installed = self.engine.presentation_styles.resolve(first)
        installed.asset("beamerthemeMSU.sty").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "integrity"):
            self.engine.presentation_profile(self.a, "talk.slides.md")

    def test_manifest_change_is_detected_even_if_assets_remain_valid(self):
        ref = self.register_style()
        self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="beamer", output_format="pdf", style=ref)
        installed = self.engine.presentation_styles.resolve(ref)
        manifest_file = installed.package_dir / "manifest.json"
        document = json.loads(manifest_file.read_text())
        document["description"] = "Unexpected changed manifest"
        manifest_file.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "manifest changed"):
            self.engine.presentation_profile(self.a, "talk.slides.md")

    def test_bad_and_unsupported_profiles_cannot_overwrite_previous_profile(self):
        before = self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html")
        for bad in (
            dict(renderer_id="beamer", output_format="pptx"),
            dict(renderer_id="unknown", output_format="pdf"),
            dict(renderer_id="reveal", output_format="html", output_name="../../escape.html"),
            dict(renderer_id="reveal", output_format="html", options={"execute": True}),
            dict(renderer_id="powerpoint", output_format="pptx", style=StyleReference("missing", "1", "beamer")),
        ):
            with self.subTest(bad=bad), self.assertRaises((PresentationError, ValueError)):
                self.engine.save_presentation_profile(self.a, "talk.slides.md", **bad)
        self.assertEqual(self.engine.presentation_profile(self.a, "talk.slides.md"), before)

    def test_bad_json_and_identity_mismatch_fail_closed(self):
        self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html")
        store = self.engine.presentation_profiles
        _, _, digest = store._identity(self.engine.project_path(self.a), self.src_a)
        profile_file = store._path(digest)
        original = json.loads(profile_file.read_text())
        for value in ("{bad", json.dumps({**original, "source": "other.md"}),
                      json.dumps({**original, "profile": {**original["profile"], "schema_version": 50}})):
            profile_file.write_text(value, encoding="utf-8")
            with self.assertRaisesRegex(PresentationError, "Invalid saved presentation profile"):
                self.engine.presentation_profile(self.a, "talk.slides.md")

    def test_symlinked_profile_root_parent_and_file_are_rejected(self):
        store = self.engine.presentation_profiles
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        store.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html")
        self.assertEqual(list(outside.iterdir()), [])
        store.root.unlink()
        self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html")
        _, _, digest = store._identity(self.engine.project_path(self.a), self.src_a)
        profile_file = store._path(digest)
        profile_file.unlink()
        profile_file.symlink_to(outside / "foreign")
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.engine.presentation_profile(self.a, "talk.slides.md")
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.engine.delete_presentation_profile(self.a, "talk.slides.md")

    def test_delete_only_selected_profile(self):
        self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html")
        self.engine.save_presentation_profile(self.b, "talk.slides.md", renderer_id="powerpoint", output_format="pptx")
        self.assertTrue(self.engine.delete_presentation_profile(self.a, "talk.slides.md"))
        self.assertFalse(self.engine.delete_presentation_profile(self.a, "talk.slides.md"))
        self.assertIsNone(self.engine.presentation_profile(self.a, "talk.slides.md"))
        self.assertEqual(self.engine.presentation_profile(self.b, "talk.slides.md")["renderer_id"], "powerpoint")

    def test_export_opt_in_uses_saved_profile_and_explicit_remains_unchanged(self):
        self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html", output_name="saved.html")
        self.assertEqual(self.src_a.read_text(), "# One")
        def fake_quarto(args, **_):
            dest = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("OK")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=fake_quarto):
            saved = self.engine.export_presentation(self.a, "talk.slides.md", use_saved_profile=True)
            direct = self.engine.export_presentation(self.a, "talk.slides.md", renderer_id="powerpoint", output_format="pptx")
            overridden_name = self.engine.export_presentation(self.a, "talk.slides.md", use_saved_profile=True, output_name="override")
        self.assertEqual(saved["path"], "builds/presentations/saved.html")
        self.assertTrue(saved["saved_profile_applied"])
        self.assertEqual(direct["path"], "builds/presentations/talk.pptx")
        self.assertNotIn("saved_profile_applied", direct)
        self.assertEqual(overridden_name["path"], "builds/presentations/override.html")
        self.assertEqual(self.engine.presentation_profile(self.a, "talk.slides.md")["output_name"], "saved.html")
        self.assertEqual(self.src_a.read_text(), "# One")

    def test_saved_styled_beamer_export_uses_pinned_theme_and_stages_assets(self):
        import os
        ref = self.register_style("1.0.0")
        self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="beamer", output_format="pdf", style=ref)
        self.register_style("2.0.0")
        calls = []
        def fake_render(args, *, env, **_):
            self.assertEqual(args[args.index("-M") + 1], "theme:MSU")
            stage = Path(env["TEXINPUTS"].split(os.pathsep)[0][:-2])
            self.assertEqual((stage / "beamerthemeMSU.sty").read_text(encoding="utf-8"), "% custom")
            calls.append(stage)
            dest = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
            dest.write_bytes(b"%PDF-1.4")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(self.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch.object(self.engine.notebook_exports, "_has_latex", return_value=True), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=fake_render):
            result = self.engine.export_presentation(self.a, "talk.slides.md", use_saved_profile=True)
        self.assertEqual(result["style"]["version"], "1.0.0")
        self.assertEqual(result["path"], "builds/presentations/talk.pdf")
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].exists())

    def test_profile_fails_closed_on_parent_symlink(self):
        store = self.engine.presentation_profiles
        store.root.mkdir()
        outside = Path(self.temp.name) / "other-profiles"
        outside.mkdir()
        (store.root / "profiles").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html")
        self.assertEqual(list(outside.iterdir()), [])

    def test_opt_in_requires_profile_and_forbids_ambiguous_overrides(self):
        with self.assertRaisesRegex(PresentationError, "No saved"):
            self.engine.export_presentation(self.a, "talk.slides.md", use_saved_profile=True)
        self.engine.save_presentation_profile(self.a, "talk.slides.md", renderer_id="reveal", output_format="html")
        with self.assertRaisesRegex(PresentationError, "cannot be mixed"):
            self.engine.export_presentation(self.a, "talk.slides.md", renderer_id="beamer", use_saved_profile=True)
        with self.assertRaisesRegex(PresentationError, "require"):
            self.engine.export_presentation(self.a, "talk.slides.md")


@unittest.skipUnless(importlib.util.find_spec("flask") is not None, "Flask is not installed")
class PresentationProfileHttpTests(unittest.TestCase):
    def setUp(self):
        self.web = importlib.import_module("tech_documents.web.app")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_engine = self.web.engine
        self.web.engine = DocumentEngine(Path(self.temp.name) / "host")
        self.addCleanup(self.web.engine.notebooks.shutdown_all)
        self.project = self.web.engine.create_project("demo")
        self.web.engine.create_file(self.project, "talk.md", "# Talk")
        self.client = self.web.app.test_client()
        self.url = f"/api/presentations/{self.project}/talk.md/profile"

    def tearDown(self):
        self.web.engine = self.old_engine

    def test_profile_put_get_delete_and_export_opt_in(self):
        self.assertIsNone(self.client.get(self.url).get_json()["profile"])
        response = self.client.put(self.url, json={"renderer": "reveal", "format": "html", "output_name": "mine.html"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(self.url).get_json()["profile"]["renderer_id"], "reveal")
        def fake_quarto(args, **_):
            output = Path(args[args.index("--output-dir") + 1]) / args[args.index("--output") + 1]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok")
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(self.web.engine.notebook_exports, "_quarto", return_value="quarto"), \
             patch("tech_documents.presentations.legacy_adapters.subprocess.run", side_effect=fake_quarto):
            exported = self.client.post(f"/api/presentations/{self.project}/talk.md/exports", json={"use_saved_profile": True})
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.get_json()["path"], "builds/presentations/mine.html")
        self.assertTrue(self.client.delete(self.url).get_json()["deleted"])
        self.assertIsNone(self.client.get(self.url).get_json()["profile"])

    def test_invalid_payloads_and_ambiguous_export(self):
        self.assertEqual(self.client.put(self.url, json=["invalid"]).status_code, 400)
        self.assertEqual(self.client.put(self.url, json={"renderer": "beamer", "format": "pptx"}).status_code, 400)
        self.assertEqual(self.client.put(self.url, json={"renderer": "reveal", "format": "html", "typo": "ignored"}).status_code, 400)
        self.assertEqual(self.client.put(self.url, json={"renderer": "reveal", "format": "html", "options": {"execute": True}}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/presentations/{self.project}/talk.md/exports",
                                          json={"use_saved_profile": "true"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/presentations/{self.project}/talk.md/exports",
                                          json={"use_saved_profile": True, "renderer": "beamer"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/presentations/{self.project}/talk.md/exports",
                                          json=["invalid"]).status_code, 400)


if __name__ == "__main__":
    unittest.main()
