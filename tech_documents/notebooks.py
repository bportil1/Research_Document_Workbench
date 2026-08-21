from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import atexit
import os
import sys
import threading
import time
from typing import Any

from .errors import DocumentEngineError, ItemNotFoundError


class NotebookDependencyError(DocumentEngineError):
    status_code = 503


class NotebookExecutionError(DocumentEngineError):
    status_code = 500


def _nbformat():
    try:
        import nbformat
    except ImportError as exc:  # pragma: no cover - exercised in installations without notebook extras
        raise NotebookDependencyError(
            "Notebook support requires nbformat. Install the Workbench notebook dependencies."
        ) from exc
    return nbformat


def _jupyter_client():
    try:
        from jupyter_client import KernelManager
    except ImportError as exc:  # pragma: no cover - exercised in installations without notebook extras
        raise NotebookDependencyError(
            "Notebook execution requires jupyter_client and ipykernel. Install the Workbench notebook dependencies."
        ) from exc
    return KernelManager


def notebook_dependencies() -> dict[str, bool]:
    availability = {"nbformat": False, "jupyter_client": False, "ipykernel": False}
    try:
        import nbformat  # noqa: F401
        availability["nbformat"] = True
    except ImportError:
        pass
    try:
        import jupyter_client  # noqa: F401
        availability["jupyter_client"] = True
    except ImportError:
        pass
    try:
        import ipykernel  # noqa: F401
        availability["ipykernel"] = True
    except ImportError:
        pass
    availability["available"] = all(availability.values())
    return availability


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass
class _KernelSession:
    manager: Any
    client: Any
    cwd: Path
    started_at: float


class NotebookRuntime:
    """Notebook storage and local Python-kernel execution.

    Jupyter dependencies are loaded lazily so importing the reusable
    ``tech_documents`` package does not start or require a notebook runtime.
    Kernel sessions are local processes and are keyed by notebook path.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _KernelSession] = {}
        self._lock = threading.RLock()
        atexit.register(self.shutdown_all)

    @staticmethod
    def _key(path: Path) -> str:
        return str(path.resolve())

    def create(self, path: Path) -> None:
        nbformat = _nbformat()
        notebook = nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_markdown_cell("# Notebook\n\nStart documenting the analysis here."),
                nbformat.v4.new_code_cell(""),
            ],
            metadata={
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                },
                "language_info": {"name": "python"},
            },
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(notebook, path)

    def load(self, path: Path) -> dict[str, Any]:
        if not path.exists() or not path.is_file():
            raise ItemNotFoundError("Notebook does not exist.")
        nbformat = _nbformat()
        try:
            notebook = nbformat.read(path, as_version=4)
        except Exception as exc:
            raise DocumentEngineError(f"Unable to read notebook: {exc}") from exc
        return _jsonable(notebook)

    def save(self, path: Path, notebook_data: dict[str, Any]) -> None:
        if not isinstance(notebook_data, dict):
            raise DocumentEngineError("Notebook data must be an object.")
        nbformat = _nbformat()
        try:
            notebook = nbformat.from_dict(notebook_data)
            if int(getattr(notebook, "nbformat", 4) or 4) != 4:
                notebook = nbformat.convert(notebook, 4)
            nbformat.validate(notebook)
            nbformat.write(notebook, path)
        except Exception as exc:
            raise DocumentEngineError(f"Unable to save notebook: {exc}") from exc

    def _session(self, path: Path, cwd: Path) -> _KernelSession:
        key = self._key(path)
        with self._lock:
            existing = self._sessions.get(key)
            if existing is not None:
                return existing

            KernelManager = _jupyter_client()
            manager = KernelManager(kernel_name="python3")
            kernel_env = os.environ.copy()
            interpreter_dir = str(Path(sys.executable).resolve().parent)
            kernel_env["PATH"] = interpreter_dir + os.pathsep + kernel_env.get("PATH", "")
            try:
                manager.start_kernel(cwd=str(cwd), env=kernel_env)
                client = manager.client()
                client.start_channels()
                client.wait_for_ready(timeout=20)
            except Exception as exc:
                try:
                    manager.shutdown_kernel(now=True)
                except Exception:
                    pass
                raise NotebookExecutionError(f"Unable to start the Python kernel: {exc}") from exc

            session = _KernelSession(
                manager=manager,
                client=client,
                cwd=cwd,
                started_at=time.time(),
            )
            self._sessions[key] = session
            return session

    def status(self, path: Path) -> dict[str, Any]:
        deps = notebook_dependencies()
        with self._lock:
            session = self._sessions.get(self._key(path))
        return {
            "available": deps["available"],
            "dependencies": deps,
            "running": session is not None,
            "kernel": "python3",
            "python_executable": sys.executable,
            "started_at": session.started_at if session is not None else None,
        }

    def execute(self, path: Path, cwd: Path, source: str, *, timeout: float = 120.0) -> dict[str, Any]:
        if not isinstance(source, str):
            raise DocumentEngineError("Notebook cell source must be text.")
        session = self._session(path, cwd)
        client = session.client
        try:
            msg_id = client.execute(
                source,
                silent=False,
                store_history=True,
                allow_stdin=False,
                stop_on_error=False,
            )
        except Exception as exc:
            raise NotebookExecutionError(f"Unable to submit notebook cell: {exc}") from exc

        outputs: list[dict[str, Any]] = []
        execution_count: int | None = None
        deadline = time.monotonic() + max(1.0, float(timeout))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NotebookExecutionError("Notebook cell execution timed out.")
            try:
                message = client.get_iopub_msg(timeout=min(1.0, remaining))
            except Exception as exc:
                if time.monotonic() >= deadline:
                    raise NotebookExecutionError("Notebook cell execution timed out.") from exc
                continue

            if message.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            msg_type = message.get("header", {}).get("msg_type")
            content = message.get("content", {})

            if msg_type == "status" and content.get("execution_state") == "idle":
                break
            if msg_type == "execute_input":
                execution_count = content.get("execution_count")
            elif msg_type == "stream":
                outputs.append(
                    {
                        "output_type": "stream",
                        "name": content.get("name", "stdout"),
                        "text": content.get("text", ""),
                    }
                )
            elif msg_type == "clear_output":
                outputs.clear()
            elif msg_type in {"display_data", "execute_result"}:
                output = {
                    "output_type": msg_type,
                    "data": _jsonable(content.get("data", {})),
                    "metadata": _jsonable(content.get("metadata", {})),
                }
                if msg_type == "execute_result":
                    count = content.get("execution_count")
                    output["execution_count"] = count
                    execution_count = count
                outputs.append(output)
            elif msg_type == "error":
                outputs.append(
                    {
                        "output_type": "error",
                        "ename": content.get("ename", "Error"),
                        "evalue": content.get("evalue", ""),
                        "traceback": _jsonable(content.get("traceback", [])),
                    }
                )

        return {
            "ok": True,
            "execution_count": execution_count,
            "outputs": outputs,
            "kernel": self.status(path),
        }

    def interrupt(self, path: Path) -> bool:
        with self._lock:
            session = self._sessions.get(self._key(path))
        if session is None:
            return False
        try:
            session.manager.interrupt_kernel()
        except Exception as exc:
            raise NotebookExecutionError(f"Unable to interrupt the Python kernel: {exc}") from exc
        return True

    def restart(self, path: Path, cwd: Path) -> dict[str, Any]:
        key = self._key(path)
        with self._lock:
            session = self._sessions.get(key)
        if session is None:
            self._session(path, cwd)
            return self.status(path)
        try:
            session.manager.restart_kernel(now=True)
            session.client.wait_for_ready(timeout=20)
            session.started_at = time.time()
        except Exception as exc:
            raise NotebookExecutionError(f"Unable to restart the Python kernel: {exc}") from exc
        return self.status(path)

    def shutdown(self, path: Path) -> bool:
        key = self._key(path)
        with self._lock:
            session = self._sessions.pop(key, None)
        if session is None:
            return False
        try:
            session.client.stop_channels()
        except Exception:
            pass
        try:
            session.manager.shutdown_kernel(now=True)
        except Exception:
            pass
        return True

    def shutdown_under(self, path: Path) -> int:
        root = path.resolve()
        with self._lock:
            keys = [
                key for key in self._sessions
                if Path(key) == root or root in Path(key).parents
            ]
        count = 0
        for key in keys:
            count += int(self.shutdown(Path(key)))
        return count

    def shutdown_all(self) -> int:
        with self._lock:
            keys = list(self._sessions)
        count = 0
        for key in keys:
            count += int(self.shutdown(Path(key)))
        return count


__all__ = [
    "NotebookDependencyError",
    "NotebookExecutionError",
    "NotebookRuntime",
    "notebook_dependencies",
]
