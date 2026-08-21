from __future__ import annotations

from collections.abc import Sequence


class MemoryValidationError(ValueError):
    def __init__(
        self,
        status: str,
        message: str,
        *,
        path: str | None = None,
        latest: dict[str, object] | None = None,
        applied_paths: Sequence[str] | None = None,
    ):
        self.status = status
        self.path = path
        self.latest = latest
        self.applied_paths = list(applied_paths or [])
        super().__init__(message)

    def response(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status, "message": str(self)}
        if self.path is not None:
            payload["path"] = self.path
        if self.latest is not None:
            payload["latest"] = self.latest
        if self.applied_paths:
            payload["applied_paths"] = self.applied_paths
        return payload
