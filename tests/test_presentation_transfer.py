from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tech_documents.api import DocumentEngine


class PresentationTransferTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.engine = DocumentEngine(self.tempdir.name)
        self.project = self.engine.create_project("demo")

    def tearDown(self):
        self.engine.notebooks.shutdown_all()
        self.tempdir.cleanup()

    def test_notebook_to_markdown_backup_preserves_slide_roles_and_static_code(self):
        self.engine.create_file(self.project, "talk.ipynb")
        data = self.engine.read_notebook(self.project, "talk.ipynb")["notebook"]
        data["cells"] = [
            {"cell_type":"markdown","id":"a","metadata":{},"source":"# One"},
            {"cell_type":"markdown","id":"b","metadata":{"slideshow":{"slide_type":"subslide"}},"source":"## Two"},
            {"cell_type":"code","id":"c","metadata":{},"source":"print('x')","execution_count":1,"outputs":[{"output_type":"stream","name":"stdout","text":"x\\n"}]},
        ]
        self.engine.save_notebook(self.project, "talk.ipynb", data)
        result = self.engine.convert_presentation(self.project, "talk.ipynb", target="markdown")
        output = self.engine.project_path(self.project) / result["path"]
        text = output.read_text(encoding="utf-8")
        self.assertIn("format: workbench-slides", text)
        self.assertIn("workbench-slide-role: slide", text)
        self.assertIn("workbench-slide-role: subslide", text)
        self.assertIn("```python", text)
        self.assertIn("```text", text)
        self.assertEqual(result["details"]["static_outputs"], 1)

    def test_markdown_to_notebook_round_trip_restores_supported_roles(self):
        self.engine.create_file(self.project, "talk.slides.md", """---\npresentation: true\n---\n\n<!-- workbench-slide-role: slide -->\n\n# One\n\n---\n\n<!-- workbench-slide-role: fragment -->\n\nMore\n""")
        result = self.engine.convert_presentation(self.project, "talk.slides.md", target="notebook")
        path = self.engine.project_path(self.project) / result["path"]
        import nbformat
        nb = nbformat.read(path, as_version=4)
        self.assertEqual(len(nb.cells), 2)
        self.assertEqual(nb.cells[0].metadata.slideshow.slide_type, "slide")
        self.assertEqual(nb.cells[1].metadata.slideshow.slide_type, "fragment")
        self.assertEqual(nb.cells[0].source, "# One")

    def test_adjacent_backup_creates_paired_artifact_without_overwrite(self):
        self.engine.create_file(self.project, "talk.ipynb")
        result = self.engine.convert_presentation(
            self.project,
            "talk.ipynb",
            target="markdown",
            location="adjacent",
        )
        self.assertEqual(result["path"], "talk.slides.md")
        self.assertEqual(result["location"], "adjacent")
        self.assertTrue((self.engine.project_path(self.project) / "talk.slides.md").is_file())
        with self.assertRaises(Exception) as raised:
            self.engine.convert_presentation(
                self.project,
                "talk.ipynb",
                target="markdown",
                location="adjacent",
            )
        self.assertIn("already exists", str(raised.exception))

    def test_conversion_reports_static_fallback_warnings(self):
        self.engine.create_file(self.project, "warn.ipynb")
        data = self.engine.read_notebook(self.project, "warn.ipynb")["notebook"]
        data["cells"] = [
            {
                "cell_type": "code",
                "id": "code",
                "metadata": {},
                "source": "print('x')",
                "execution_count": 1,
                "outputs": [{"output_type": "stream", "name": "stdout", "text": "x\\n"}],
            }
        ]
        self.engine.save_notebook(self.project, "warn.ipynb", data)
        result = self.engine.convert_presentation(self.project, "warn.ipynb", target="markdown")
        self.assertTrue(result["details"]["warnings"])
        self.assertIn("static Markdown fallbacks", result["details"]["warnings"][0])


class PresentationRecoveryHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.engine = DocumentEngine(self.tempdir.name)
        self.project = self.engine.create_project("recovery")

    def tearDown(self):
        self.engine.notebooks.shutdown_all()
        self.tempdir.cleanup()

    def test_markdown_split_only_treats_yaml_like_header_as_front_matter(self):
        from tech_documents.presentation_transfer import split_presentation_markdown

        source = "---\n# This is slide content\n---\n# Second\n"
        self.assertEqual(split_presentation_markdown(source), ["# This is slide content", "# Second"])

        source_with_front_matter = (
            "---\npresentation: true\nformat: workbench-slides\n---\n\n"
            "# First\n\n---\n\n# Second\n"
        )
        self.assertEqual(split_presentation_markdown(source_with_front_matter), ["# First", "# Second"])

    def test_markdown_split_does_not_break_on_separator_inside_fenced_code(self):
        from tech_documents.presentation_transfer import split_presentation_markdown

        source = "# One\n\n```text\n---\n```\n\n---\n\n# Two\n"
        slides = split_presentation_markdown(source)
        self.assertEqual(len(slides), 2)
        self.assertIn("```text\n---\n```", slides[0])
        self.assertEqual(slides[1], "# Two")

    def test_round_trip_keeps_supported_presentation_roles(self):
        self.engine.create_file(self.project, "roles.slides.md", """---
presentation: true
format: workbench-slides
---

<!-- workbench-slide-role: slide -->

# Main

---

<!-- workbench-slide-role: subslide -->

## Detail

---

<!-- workbench-slide-role: fragment -->

Incremental point

---

<!-- workbench-slide-role: notes -->

Speaker note
""")
        result = self.engine.convert_presentation(self.project, "roles.slides.md", target="notebook")
        notebook_path = self.engine.project_path(self.project) / result["path"]
        import nbformat
        nb = nbformat.read(notebook_path, as_version=4)
        self.assertEqual(
            [cell.metadata.slideshow.slide_type for cell in nb.cells],
            ["slide", "subslide", "fragment", "notes"],
        )

        back = self.engine.convert_presentation(self.project, result["path"], target="markdown", output_name="roles-roundtrip")
        roundtrip = (self.engine.project_path(self.project) / back["path"]).read_text(encoding="utf-8")
        for role in ("slide", "subslide", "fragment", "notes"):
            self.assertIn(f"workbench-slide-role: {role}", roundtrip)

    def test_nonportable_widget_output_is_reported_in_backup_warnings(self):
        self.engine.create_file(self.project, "widget.ipynb")
        data = self.engine.read_notebook(self.project, "widget.ipynb")["notebook"]
        data["cells"] = [{
            "cell_type": "code",
            "id": "widget",
            "metadata": {},
            "source": "display(widget)",
            "execution_count": 1,
            "outputs": [{
                "output_type": "display_data",
                "metadata": {},
                "data": {"application/vnd.jupyter.widget-view+json": {"model_id": "abc"}},
            }],
        }]
        self.engine.save_notebook(self.project, "widget.ipynb", data)
        result = self.engine.convert_presentation(self.project, "widget.ipynb", target="markdown")
        self.assertEqual(result["details"]["nonportable_outputs"], 1)
        self.assertTrue(any("could not be represented" in warning for warning in result["details"]["warnings"]))
