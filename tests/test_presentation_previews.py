"""PS-09: local rendered theme previews and safety/compatibility contracts."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tech_documents.api import DocumentEngine
from tech_documents.presentations import PresentationError, PresentationPreviewService, PresentationStyleRegistry, StyleReference
from tech_documents.presentations.previews import BeamerPreviewProvider


class FakeBeamerPreview:
    style_kind = "beamer"

    def __init__(self):
        self.runs = 0
        self.enabled = True

    def availability(self):
        return (True, "") if self.enabled else (False, "Local rendering tools are unavailable.")

    def render(self, installed, destination):
        self.runs += 1
        destination.mkdir()
        (destination / "preview.pdf").write_bytes(b"%PDF sample")
        (destination / "slide-1.png").write_bytes(b"PNG sample 1")
        (destination / "slide-2.png").write_bytes(b"PNG sample 2")


class PreviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.styles = PresentationStyleRegistry(root / "styles")
        self.provider = FakeBeamerPreview()
        self.service = PresentationPreviewService(self.styles, root / "previews", (self.provider,))
        source = root / "source"
        source.mkdir()
        (source / "beamerthemeExample.sty").write_text("% test", encoding="utf-8")
        self.manifest = self.styles.install(
            identifier="example", version="1.0.0", kind="beamer", label="Example",
            renderer_ids=["beamer"], source_dir=source,
            entrypoint="beamerthemeExample.sty", asset_paths=["beamerthemeExample.sty"],
        )
        self.reference = self.manifest.reference
        self.root = root

    def test_explicit_generation_and_read_only_cache(self):
        first = self.service.status(self.reference)
        self.assertTrue(first.available)
        self.assertFalse(first.cached)
        self.assertEqual(self.provider.runs, 0)
        generated = self.service.generate(self.reference)
        self.assertTrue(generated.cached)
        self.assertEqual(self.provider.runs, 1)
        self.assertEqual(generated.fingerprint, first.fingerprint)
        self.assertEqual(self.service.file(self.reference, "preview.pdf").read_bytes(), b"%PDF sample")
        self.assertEqual(len(self.service.status(self.reference).as_dict()["pages"]), 2)
        self.service.generate(self.reference)
        self.assertEqual(self.provider.runs, 1, "Cached result should not invoke compiler again")

    def test_version_and_manifest_invalidation(self):
        original = self.service.generate(self.reference)
        other = self.styles.install(identifier="example", version="2.0.0", kind="beamer",
                                    label="Example 2", renderer_ids=["beamer"],
                                    source_dir=self.root / "source", asset_paths=["beamerthemeExample.sty"],
                                    entrypoint="beamerthemeExample.sty")
        self.assertFalse(self.service.status(other.reference).cached)
        self.assertNotEqual(self.service.status(other.reference).fingerprint, original.fingerprint)
        self.styles.uninstall(self.reference)
        with self.assertRaisesRegex(PresentationError, "not installed"):
            self.service.file(self.reference, "preview.pdf")
        with self.assertRaisesRegex(PresentationError, "not installed"):
            self.service.status(self.reference)

    def test_tool_unavailable_but_cached_preview_remains_readable(self):
        self.service.generate(self.reference)
        self.provider.enabled = False
        status = self.service.status(self.reference)
        self.assertFalse(status.available)
        self.assertTrue(status.cached)
        with self.assertRaisesRegex(PresentationError, "unavailable"):
            self.service.generate(self.reference)
        self.assertTrue(self.service.file(self.reference, "slide-2.png").is_file())

    def test_invalid_asset_and_symlink_storage_rejected(self):
        with self.assertRaisesRegex(PresentationError, "Unknown"):
            self.service.file(self.reference, "../../etc/passwd")
        outside = self.root / "outside"
        outside.mkdir()
        self.service.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.service.status(self.reference)
        with self.assertRaisesRegex(PresentationError, "symlink"):
            self.service.generate(self.reference)
        self.assertEqual(list(outside.iterdir()), [])

    def test_asset_corruption_blocks_cache_and_compilation(self):
        self.service.generate(self.reference)
        item = self.styles.resolve(self.reference).asset("beamerthemeExample.sty")
        item.write_text("changed")
        with self.assertRaisesRegex(PresentationError, "integrity"):
            self.service.status(self.reference)
        with self.assertRaisesRegex(PresentationError, "integrity"):
            self.service.generate(self.reference)

    def test_missing_provider_returns_unavailable_without_compiling(self):
        self.styles.install(identifier="webstyle", version="1", kind="reveal", label="Web",
                            renderer_ids=["reveal"])
        ref = StyleReference("webstyle", "1", "reveal")
        result = self.service.status(ref)
        self.assertFalse(result.available)
        self.assertFalse(result.cached)
        with self.assertRaisesRegex(PresentationError, "No preview provider"):
            self.service.generate(ref)

    def test_beamer_provider_commands_disable_shell_escape(self):
        # A mock integration verifies the preview compiler invocation contract.
        with patch.object(BeamerPreviewProvider, "_run") as run:
            # The mock doesn't produce PDF/PNGs, so rendering fails *after*
            # the compiler arguments have been recorded.
            provider = BeamerPreviewProvider()
            provider.bind_registry(self.styles)
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(PresentationError, "PDF is missing"):
                    provider.render(self.styles.resolve(self.reference), Path(temp) / "output")
            self.assertTrue(run.called)
            self.assertIn("-no-shell-escape", run.call_args_list[0].args[0])
            self.assertFalse(any("make" in arg for arg in run.call_args_list[0].args[0]))


class PresentationPreviewFrontEndTests(unittest.TestCase):
    def test_dom_integration_and_explicit_generation(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "tech_documents/web/templates/index.html").read_text()
        js = (root / "tech_documents/web/static/app.js").read_text()
        for item in ("presentationStylePreviewPanel", "presentationStylePreviewBtn", "presentationStylePreviewImages", "presentationStylePreviewPdf", "presentationStylePreviewStatus"):
            self.assertIn(f'id="{item}"', html)
        self.assertIn('function loadPresentationStylePreview()', js)
        self.assertIn('function generatePresentationStylePreview()', js)
        self.assertIn('method: "POST"', js)
        self.assertIn('presentationStylePreviewBtn?.addEventListener("click"', js)
        self.assertNotIn('loadPresentationStylePreview({ method: "POST"', js)


@unittest.skipUnless(importlib.util.find_spec("flask"), "Flask not installed")
class PreviewHttpTests(unittest.TestCase):
    def setUp(self):
        self.web = importlib.import_module("tech_documents.web.app")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original = self.web.engine
        self.web.engine = DocumentEngine(self.temp.name)
        self.addCleanup(setattr, self.web, "engine", self.original)
        self.addCleanup(self.web.engine.notebooks.shutdown_all)
        root = Path(self.temp.name) / "test-style"
        root.mkdir()
        (root / "beamerthemeExample.sty").write_text("% sample")
        self.ref = self.web.engine.presentation_styles.install(identifier="example", version="1.0", kind="beamer",
            label="Example", renderer_ids=["beamer"], source_dir=root,
            entrypoint="beamerthemeExample.sty", asset_paths=["beamerthemeExample.sty"]).reference
        self.client = self.web.app.test_client()
        self.url = "/api/presentation-styles/beamer/example/1.0/preview"

    def test_lookup_never_renders_and_file_whitelist(self):
        with patch.object(self.web.engine.presentation_previews, "generate") as generate:
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertFalse(response.get_json()["cached"])
            generate.assert_not_called()
        bad = self.client.get(self.url + "/files/secret")
        self.assertEqual(bad.status_code, 400)

    def test_generation_and_local_file_retrieval(self):
        fake = FakeBeamerPreview()
        self.web.engine.presentation_previews._providers["beamer"] = fake
        preview = self.client.post(self.url)
        self.assertEqual(preview.status_code, 200, preview.get_json())
        data = preview.get_json()
        self.assertEqual(len(data["images"]), 2)
        self.assertTrue(data["pdf_url"].endswith("/preview.pdf"))
        pdf = self.client.get(data["pdf_url"])
        self.assertEqual(pdf.data, b"%PDF sample")
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertEqual(pdf.headers["Cache-Control"], "private, no-store")
        self.assertEqual(fake.runs, 1)
        self.client.get(self.url)
        self.assertEqual(fake.runs, 1)


if __name__ == "__main__":
    unittest.main()
