"""PS-01: shared presentation contracts; no LaTeX, Quarto or Flask required."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tech_documents import DocumentEngine
from tech_documents.presentations import (
    PresentationError,
    PresentationExportRequest,
    PresentationExportResult,
    PresentationService,
    RendererCapabilities,
    StyleReference,
)


class StubRenderer:
    renderer_id = "beamer"

    def __init__(self, *, available=True, output_outside=False):
        self.available = available
        self.output_outside = output_outside
        self.called = 0

    def capabilities(self):
        return RendererCapabilities(
            renderer_id=self.renderer_id,
            label="Test Beamer",
            source_kinds=("markdown", "notebook", "latex"),
            output_formats=("pdf",),
            style_kinds=("beamer",),
            available=self.available,
            reason="Local test renderer is disabled." if not self.available else "",
        )

    def render(self, request):
        self.called += 1
        destination = request.project_root / "builds" / "slides.pdf"
        if self.output_outside:
            destination = request.project_root.parent / "outside.pdf"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"%PDF-1.4\n")
        return PresentationExportResult("beamer", "pdf", destination)


class PresentationFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.markdown = self.project / "talk.md"
        self.markdown.write_text("# Hello\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, **overrides):
        options = dict(
            source_path=self.markdown,
            project_root=self.project,
            source_kind="markdown",
            renderer_id="beamer",
            output_format="pdf",
            style=StyleReference("msu", "1.0", "beamer"),
        )
        options.update(overrides)
        return PresentationExportRequest(**options)

    def test_planned_renderers_are_explicitly_unavailable(self):
        service = PresentationService()
        catalog = {entry["id"]: entry for entry in service.capabilities()}
        self.assertEqual(set(catalog), {"beamer", "reveal", "powerpoint"})
        self.assertTrue(all(not entry["available"] and entry["reason"] for entry in catalog.values()))
        self.assertEqual(service.compatible_renderers(source_kind="markdown"), [])
        self.assertEqual(
            [entry["id"] for entry in service.compatible_renderers(
                source_kind="latex", output_format="pdf", available_only=False)],
            ["beamer"],
        )
        with self.assertRaisesRegex(PresentationError, "not connected"):
            service.export(self.request())

    def test_registered_adapter_discovery_and_export(self):
        renderer = StubRenderer()
        service = PresentationService([renderer])
        self.assertEqual(
            [entry["id"] for entry in service.compatible_renderers(
                source_kind="markdown", output_format="pdf", style_kind="beamer")],
            ["beamer"],
        )
        result = service.export(self.request())
        self.assertEqual(result.renderer_id, "beamer")
        self.assertTrue(result.output_path.is_file())
        self.assertEqual(renderer.called, 1)
        self.assertEqual(self.markdown.read_text(encoding="utf-8"), "# Hello\n")

    def test_rejects_unsupported_pairs_styles_and_unavailable_adapter(self):
        renderer = StubRenderer()
        service = PresentationService([renderer])
        for req in (
            self.request(output_format="html"),
            self.request(source_kind="slides"),
            self.request(style=StyleReference("web", "1", "reveal")),
        ):
            with self.assertRaisesRegex(PresentationError, "does not support"):
                service.export(req)
        self.assertEqual(renderer.called, 0)
        renderer.available = False
        with self.assertRaisesRegex(PresentationError, "disabled"):
            service.export(self.request())
        self.assertEqual(renderer.called, 0)

    def test_validates_source_and_output_containment(self):
        renderer = StubRenderer()
        service = PresentationService([renderer])
        with self.assertRaisesRegex(PresentationError, "source file does not exist"):
            service.export(self.request(source_path=self.project / "missing.md"))
        outside = self.root / "outside.md"
        outside.write_text("# Outside", encoding="utf-8")
        with self.assertRaisesRegex(PresentationError, "inside the project"):
            service.export(self.request(source_path=outside))
        renderer.output_outside = True
        with self.assertRaisesRegex(PresentationError, "outside the project"):
            service.export(self.request())

    def test_rejects_duplicate_registration_and_invalid_renderer_contract(self):
        service = PresentationService([StubRenderer()])
        with self.assertRaisesRegex(PresentationError, "already registered"):
            service.register(StubRenderer())

        class Mismatched(StubRenderer):
            renderer_id = "different"

            def capabilities(self):
                return StubRenderer().capabilities()

        with self.assertRaisesRegex(PresentationError, "does not match"):
            PresentationService([Mismatched()])

    def test_core_engine_exposes_foundation_without_changing_notebook_exports(self):
        engine = DocumentEngine(self.root / "engine")
        descriptions = engine.presentation_renderer_capabilities()
        self.assertTrue(any(item["id"] == "beamer" for item in descriptions))
        # PS-02 connects real adapters: availability depends on installed local
        # Quarto, TeX, nbconvert and vendored Reveal.js assets.
        notebook_caps = {item["id"]: item for item in engine.notebook_exports.capabilities()["formats"]}
        by_renderer = {item["id"]: item for item in descriptions}
        self.assertEqual(by_renderer["beamer"]["available"],
                         notebook_caps["beamer"]["available"] or
                         bool(__import__("shutil").which("latexmk") or __import__("shutil").which("tectonic")))
        self.assertEqual(by_renderer["powerpoint"]["available"], notebook_caps["pptx"]["available"])
        self.assertEqual(by_renderer["reveal"]["available"],
                         notebook_caps["reveal"]["available"] or bool(engine.notebook_exports._quarto()))
        self.assertTrue(hasattr(engine.notebook_exports, "export"))
        self.assertTrue(hasattr(engine, "presentations"))

    def test_contract_validation(self):
        with self.assertRaises(ValueError):
            StyleReference("../escape", "1", "beamer")
        with self.assertRaises(ValueError):
            self.request(source_kind="Markdown")
        with self.assertRaises(ValueError):
            self.request(options={"include": []})
        with self.assertRaises(ValueError):
            RendererCapabilities(
                "fake", "Fake", ("markdown", "markdown"), ("pdf",),
            )
        with self.assertRaises(ValueError):
            RendererCapabilities("fake", "Fake", ("markdown",), ("pdf",), available=False, reason="")


if __name__ == "__main__":
    unittest.main()
