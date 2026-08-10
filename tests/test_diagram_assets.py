import unittest

from diagram_assets import (
    insert_figure_reference,
    relative_asset_path,
)


class DiagramAssetTests(unittest.TestCase):
    def test_relative_path_from_root_document(self):
        self.assertEqual(
            relative_asset_path("paper.tex", "figures/architecture.pdf"),
            "figures/architecture.pdf",
        )

    def test_relative_path_from_nested_document(self):
        self.assertEqual(
            relative_asset_path("sections/method.tex", "figures/architecture.pdf"),
            "../figures/architecture.pdf",
        )

    def test_markdown_insertion(self):
        result = insert_figure_reference(
            "# Architecture\n",
            target_file="notes.md",
            asset_file="figures/architecture.svg",
            caption="FarmBot architecture",
        )
        self.assertIn("![FarmBot architecture](figures/architecture.svg)", result.content)
        self.assertFalse(result.already_present)

    def test_latex_inserts_before_end_document(self):
        source = "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\nText\n\\end{document}\n"
        result = insert_figure_reference(
            source,
            target_file="paper.tex",
            asset_file="figures/architecture.pdf",
            caption="FarmBot architecture.",
            label="fig:farmbot-architecture",
            figure_mode="double",
        )
        self.assertIn("\\begin{figure*}[t]", result.content)
        self.assertIn("\\includegraphics[width=\\textwidth]{figures/architecture.pdf}", result.content)
        self.assertLess(result.content.index("\\begin{figure*}"), result.content.index("\\end{document}"))
        self.assertEqual(result.label, "fig:farmbot-architecture")

    def test_latex_warns_without_graphicx(self):
        result = insert_figure_reference(
            "\\begin{document}\n\\end{document}\n",
            target_file="paper.tex",
            asset_file="figures/architecture.png",
        )
        self.assertIn("graphicx", result.warning)

    def test_duplicate_reference_is_not_added_twice(self):
        source = "![Diagram](figures/architecture.svg)\n"
        result = insert_figure_reference(
            source,
            target_file="notes.md",
            asset_file="figures/architecture.svg",
        )
        self.assertTrue(result.already_present)
        self.assertEqual(result.content, source)

    def test_reject_markdown_pdf(self):
        with self.assertRaises(ValueError):
            insert_figure_reference(
                "# Notes\n",
                target_file="notes.md",
                asset_file="figures/architecture.pdf",
            )


if __name__ == "__main__":
    unittest.main()
