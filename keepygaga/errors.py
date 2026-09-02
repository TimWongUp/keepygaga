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
        current: int | None = None,
        limit: int | None = None,
        recovery: str | None = None,
        scope: str | None = None,
        repairable: bool | None = None,
        raw: str | None = None,
        version: str | None = None,
    ):
        self.status = status
        self.path = path
        self.latest = latest
        self.applied_paths = list(applied_paths or [])
        self.current = current
        self.limit = limit
        self.recovery = recovery
        self.scope = scope
        self.repairable = repairable
        self.raw = raw
        self.version = version
        super().__init__(message)

    def response(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status, "message": str(self)}
        optional: tuple[tuple[str, object | None], ...] = (
            ("path", self.path),
            ("latest", self.latest),
            ("applied_paths", self.applied_paths or None),
            ("current", self.current),
            ("limit", self.limit),
            ("recovery", self.recovery),
            ("scope", self.scope),
            ("repairable", self.repairable),
            ("raw", self.raw),
            ("version", self.version),
        )
        payload.update((key, value) for key, value in optional if value is not None)
        return payload
