"""Optional, dependency-free PAH orchestration contract for Document Workbench.

The host owns processes and routing; this adapter only publishes how to start
an independent Workbench.  No PAH or Flask code is imported here.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Mapping


class WorkbenchRuntimeAdapter:
    module_id = "tech_documents"

    def status(self, *, context: Any = None) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "available": True,
            "running": False,  # PAH tracks individual process records, not this adapter.
            "launchable": True,
            "message": "Use PAH Instances to launch independently managed Workbench windows.",
        }

    def launch(self, *, context: Any = None, detached: bool = False) -> dict[str, Any]:
        # This legacy module-type method cannot safely represent an instance.
        # Never spawn an unmanaged child or claim that one was launched.
        return {
            "module_id": self.module_id,
            "launched": False,
            "message": "Use New Instance in PAH's Instance Manager for this module.",
        }

    def shutdown(self, *, context: Any = None) -> None:
        # PAH's process supervisor owns targeted shutdown of child instances.
        return None

    def process_launch_spec(self, *, context: Any = None) -> dict[str, Any]:
        """Describe one independent Workbench process, without starting it.

        A PAH research workspace may offer a logical ``documents`` resource.
        This is a *suggested linked project*, never a replacement for
        Workbench's own project registry or its project-selection controls.
        """
        resources: Mapping[str, Any] = {}
        if isinstance(context, Mapping):
            value = context.get("resources")
        else:
            value = getattr(context, "resources", None)
        if isinstance(value, Mapping):
            resources = value
        env: dict[str, str] = {}
        if resources.get("documents") is not None:
            env["WORKBENCH_INITIAL_DOCUMENT_ROOT"] = str(Path(resources["documents"]).expanduser().resolve())
        return {
            "command": [sys.executable, "-m", "tech_documents.process_ui"],
            "env": env,
            "requested_port": 0,
            "ui_path": "/",
        }
