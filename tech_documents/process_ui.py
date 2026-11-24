"""PAH-supervised, independent local Research Document Workbench UI.

PAH supplies only process/port/runtime identity and an optional document root.
The module owns all project, style, compilation and notebook functionality.
Standalone ``run.py`` and ``app.py`` are deliberately unchanged.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping


def configuration_from_environment(env: Mapping[str, str]) -> dict[str, object]:
    identity = str(env.get("PAH_MODULE_INSTANCE_ID", "")).strip()
    runtime_setting = str(env.get("PAH_MODULE_RUNTIME_DIR", "")).strip()
    port_setting = str(env.get("PAH_MODULE_PORT", "")).strip()
    if not identity or not runtime_setting:
        raise RuntimeError("PAH_MODULE_INSTANCE_ID and PAH_MODULE_RUNTIME_DIR are required")
    runtime_dir = Path(runtime_setting).expanduser().resolve()
    if not runtime_dir.is_dir():
        raise RuntimeError("PAH module runtime directory does not exist")
    try:
        port = int(port_setting)
    except ValueError as exc:
        raise RuntimeError("PAH_MODULE_PORT must be a valid integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PAH_MODULE_PORT must be between 1 and 65535")

    custom_data = str(env.get("WORKBENCH_DATA_ROOT", "")).strip()
    if custom_data:
        data_root = Path(custom_data).expanduser().resolve()
    else:
        xdg_data = str(env.get("XDG_DATA_HOME", "")).strip()
        data_root = (Path(xdg_data).expanduser() if xdg_data else Path.home() / ".local" / "share") / "research-document-workbench"
        data_root = data_root.resolve()

    initial_setting = str(env.get("WORKBENCH_INITIAL_DOCUMENT_ROOT", "")).strip()
    initial_root = Path(initial_setting).expanduser().resolve() if initial_setting else None
    if initial_root is not None and (not initial_root.exists() or not initial_root.is_dir()):
        raise RuntimeError("Selected Workbench document resource is not an existing directory")

    # Persistent per-instance build files do not collide with other instances;
    # user-authored documents and linked-project registrations remain durable.
    token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return {
        "instance_id": identity,
        "runtime_dir": runtime_dir,
        "data_root": data_root,
        "builds_dir": data_root / "builds" / "instances" / token,
        "initial_document_root": initial_root,
        "port": port,
    }


def main() -> None:
    config = configuration_from_environment(os.environ)
    # Must configure before importing web.app: it constructs its default engine
    # at import time. In PAH mode this must never touch the installed source tree.
    os.environ["RDW_PROCESS_DATA_ROOT"] = str(config["data_root"])
    os.environ["RDW_PROCESS_BUILDS_ROOT"] = str(config["builds_dir"])
    from .web import app as web_app

    initial_root = config["initial_document_root"]
    if initial_root is not None:
        web_app.engine.link_project(initial_root)
    web_app.run(host="127.0.0.1", port=int(config["port"]), debug=False)


if __name__ == "__main__":
    main()
