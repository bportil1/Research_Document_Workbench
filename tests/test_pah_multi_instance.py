"""MI-01: Workbench's host-independent, multi-process launch boundary."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tech_documents import DocumentEngine, DocumentEngineError
from tech_documents.pah_integration import WorkbenchRuntimeAdapter
from tech_documents.process_ui import configuration_from_environment


def test_pah_discovery_and_process_spec_are_module_owned():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert '[project.entry-points."pah.runtimes"]' in pyproject
    assert 'tech_documents = "tech_documents.pah_integration:WorkbenchRuntimeAdapter"' in pyproject
    adapter = WorkbenchRuntimeAdapter()
    assert adapter.module_id == "tech_documents"
    spec = adapter.process_launch_spec(context={"resources": {"documents": Path("/tmp/selected-paper")}})
    assert spec == {
        "command": [sys.executable, "-m", "tech_documents.process_ui"],
        "env": {"WORKBENCH_INITIAL_DOCUMENT_ROOT": "/tmp/selected-paper"},
        "requested_port": 0,
        "ui_path": "/",
    }
    assert adapter.process_launch_spec(context=None)["env"] == {}
    assert adapter.launch(context=None)["launched"] is False


def test_two_instances_share_persistent_projects_but_not_build_roots(tmp_path: Path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    external = tmp_path / "research" / "paper-A"
    external.mkdir(parents=True)
    data = tmp_path / "persistent-data"

    def config(identity):
        return configuration_from_environment({
            "PAH_MODULE_INSTANCE_ID": identity,
            "PAH_MODULE_RUNTIME_DIR": str(runtime),
            "PAH_MODULE_PORT": "43680",
            "WORKBENCH_DATA_ROOT": str(data),
            "WORKBENCH_INITIAL_DOCUMENT_ROOT": str(external),
        })

    one = config("host:tech_documents:alpha")
    two = config("host:tech_documents:beta")
    assert one["data_root"] == two["data_root"] == data
    assert one["builds_dir"] != two["builds_dir"]
    assert one["builds_dir"].is_relative_to(data / "builds" / "instances")
    a = DocumentEngine(one["data_root"], builds_dir=one["builds_dir"])
    b = DocumentEngine(two["data_root"], builds_dir=two["builds_dir"])
    assert a.link_project(external) == b.link_project(external)
    assert [item["name"] for item in b.list_projects()] == ["paper-A"]
    a.create_project("My first paper")
    b.create_project("Second paper")
    assert {item["name"] for item in a.list_projects()} == {"paper-A", "My_first_paper", "Second_paper"}
    assert a.builds_dir != b.builds_dir
    assert not (runtime / "documents").exists()


@pytest.mark.parametrize("settings", [
    {},
    {"PAH_MODULE_INSTANCE_ID": "one"},
    {"PAH_MODULE_RUNTIME_DIR": "/tmp"},
])
def test_process_entry_requires_host_identity(settings):
    with pytest.raises(RuntimeError):
        configuration_from_environment(settings)


def test_process_port_and_resource_validation(tmp_path: Path):
    env = {
        "PAH_MODULE_INSTANCE_ID": "instance",
        "PAH_MODULE_RUNTIME_DIR": str(tmp_path),
        "PAH_MODULE_PORT": "0",
    }
    with pytest.raises(RuntimeError, match="PORT"):
        configuration_from_environment(env)
    env["PAH_MODULE_PORT"] = "55100"
    env["WORKBENCH_INITIAL_DOCUMENT_ROOT"] = str(tmp_path / "not-found")
    with pytest.raises(RuntimeError, match="document resource"):
        configuration_from_environment(env)
    env.pop("WORKBENCH_INITIAL_DOCUMENT_ROOT")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    assert configuration_from_environment(env)["data_root"] == tmp_path / "xdg" / "research-document-workbench"


def test_same_name_links_are_deterministically_separated(tmp_path: Path):
    base = tmp_path / "workbench"
    first = tmp_path / "a" / "paper"
    second = tmp_path / "b" / "paper"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    a = DocumentEngine(base)
    b = DocumentEngine(base)
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(a.link_project, first)
        f2 = executor.submit(b.link_project, second)
        names = {f1.result(), f2.result()}
    assert names == {"paper", "paper_2"}
    assert {item["name"] for item in a.list_projects()} == names


def test_two_processes_cannot_lose_linked_project_updates(tmp_path: Path):
    base = tmp_path / "workbench"
    projects = [tmp_path / "projects" / f"paper_{i}" for i in range(6)]
    for p in projects:
        p.mkdir(parents=True)
    # Separate Python interpreters validate file locking rather than shared
    # in-process locks/mocks.
    code = "from tech_documents import DocumentEngine; import sys; print(DocumentEngine(sys.argv[1]).link_project(sys.argv[2]))"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1])}
    children = [subprocess.Popen([sys.executable, "-c", code, str(base), str(p)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                for p in projects]
    for child in children:
        out, err = child.communicate(timeout=20)
        assert child.returncode == 0, err
    catalog = json.loads((base / ".workbench-projects.json").read_text())
    assert set(catalog["projects"]) == {p.name for p in projects}
    assert not list(base.glob(".workbench-projects-*.tmp"))


def test_invalid_catalog_refuses_to_drop_records(tmp_path: Path):
    engine = DocumentEngine(tmp_path)
    catalog = tmp_path / ".workbench-projects.json"
    catalog.write_text("{broken", encoding="utf-8")
    target = tmp_path / "paper"
    target.mkdir()
    with pytest.raises(DocumentEngineError, match="unreadable"):
        engine.link_project(target)
    assert catalog.read_text() == "{broken"
