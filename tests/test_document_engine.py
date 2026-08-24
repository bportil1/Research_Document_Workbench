from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
import zipfile

from tech_documents import DocumentEngine, InvalidPathError, ItemConflictError


class DocumentEngineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tempdir.name)
        self.engine = DocumentEngine(self.base)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_create_project_and_list_tree(self):
        project = self.engine.create_project("Example Project")
        self.assertEqual(project, "Example_Project")
        self.assertTrue((self.base / "documents" / project / "paper.tex").exists())
        self.assertTrue((self.base / "documents" / project / "references.bib").exists())
        self.assertTrue((self.base / "documents" / project / "notes.md").exists())
        self.assertTrue((self.base / "documents" / project / "architecture.diagram").exists())

        projects = self.engine.list_projects()
        self.assertEqual([item["name"] for item in projects], ["Example_Project"])
        indexed = {item["path"] for item in projects[0]["files"]}
        self.assertIn("paper.tex", indexed)
        self.assertIn("architecture.diagram", indexed)

    def test_file_folder_move_delete_round_trip(self):
        project = self.engine.create_project("demo")
        self.engine.create_folder(project, "sections")
        created = self.engine.create_file(project, "sections/method.md", "# Method\n")
        self.assertEqual(created, "sections/method.md")
        self.assertEqual(self.engine.read_file(project, created)["content"], "# Method\n")

        self.engine.save_file(project, created, "# Updated Method\n")
        moved = self.engine.move_item(project, created, "sections/approach.md")
        self.assertEqual(moved["destination"], "sections/approach.md")
        self.assertEqual(
            self.engine.read_file(project, "sections/approach.md")["content"],
            "# Updated Method\n",
        )
        self.engine.delete_item(project, "sections/approach.md")
        self.assertFalse((self.base / "documents" / project / "sections" / "approach.md").exists())

    def test_upload_and_archive(self):
        project = self.engine.create_project("demo")
        self.engine.create_folder(project, "assets")
        stored = self.engine.upload_file(
            project,
            "result.csv",
            io.BytesIO(b"a,b\n1,2\n"),
            "assets",
        )
        self.assertEqual(stored, "assets/result.csv")
        self.assertEqual(self.engine.asset_path(project, stored).read_bytes(), b"a,b\n1,2\n")

        archive = self.engine.archive_project(project)
        self.assertTrue(archive.exists())
        with zipfile.ZipFile(archive) as zf:
            self.assertIn("assets/result.csv", zf.namelist())

    def test_diagram_parse_save_and_markdown_insert(self):
        project = self.engine.create_project("demo")
        parsed = self.engine.parse_diagram(
            "A [service] -> B [database]\n",
            direction="LR",
            preset="research",
        )
        self.assertIn("flowchart LR", parsed["mermaid"])
        self.assertEqual(parsed["graph"]["preset"], "research")

        asset = self.engine.save_diagram_asset(
            project,
            "figures/architecture.svg",
            encoding="text",
            content="<svg></svg>",
        )
        self.assertEqual(asset.path, "figures/architecture.svg")
        inserted = self.engine.insert_diagram(
            project,
            target="notes.md",
            asset=asset.path,
            caption="Architecture",
        )
        self.assertFalse(inserted["already_present"])
        self.assertIn(
            "![Architecture](figures/architecture.svg)",
            self.engine.read_file(project, "notes.md")["content"],
        )

    def test_diagram_base64_asset(self):
        import base64

        project = self.engine.create_project("demo")
        payload = base64.b64encode(b"PNGDATA").decode("ascii")
        asset = self.engine.save_diagram_asset(
            project,
            "figures/diagram.png",
            encoding="base64",
            content=payload,
        )
        self.assertEqual(self.engine.asset_path(project, asset.path).read_bytes(), b"PNGDATA")

    def test_rejects_path_traversal(self):
        project = self.engine.create_project("demo")
        with self.assertRaises(InvalidPathError):
            self.engine.create_file(project, "../outside.md", "bad")

    def test_create_file_conflict(self):
        project = self.engine.create_project("demo")
        with self.assertRaises(ItemConflictError):
            self.engine.create_file(project, "notes.md", "duplicate")

    def test_latex_compile_when_compiler_available(self):
        if not (shutil.which("latexmk") or shutil.which("tectonic")):
            self.skipTest("No LaTeX compiler is installed.")
        project = self.engine.create_project("compile_demo")
        self.engine.save_file(
            project,
            "paper.tex",
            "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n",
        )
        result = self.engine.compile_latex(project, "paper.tex")
        self.assertTrue(result.ok, result.log)
        self.assertIsNotNone(result.pdf_path)
        self.assertTrue(result.pdf_path.exists())

    def test_core_import_does_not_load_flask(self):
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import tech_documents; "
                    "raise SystemExit(1 if 'flask' in sys.modules else 0)"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr or probe.stdout)


if __name__ == "__main__":
    unittest.main()
