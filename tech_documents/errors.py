from __future__ import annotations


class DocumentEngineError(Exception):
    """Base error raised by the reusable document engine."""

    status_code = 400

    def __init__(self, message: str = "Document operation failed.", *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class InvalidPathError(DocumentEngineError):
    status_code = 400


class UnsupportedFileTypeError(DocumentEngineError):
    status_code = 400


class ItemNotFoundError(DocumentEngineError):
    status_code = 404


class ItemConflictError(DocumentEngineError):
    status_code = 409
