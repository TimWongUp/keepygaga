from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from keepygaga.config import KeepygagaConfig, load_config
from keepygaga.memory import MemoryStore

PUBLIC_MCP_TOOLS = (
    "list",
    "read",
    "create",
    "add",
    "update",
    "move",
    "rename",
    "delete",
)
DOCTOR_SCHEMA = "keepygaga-doctor-v8"


def _check(
    checks: list[dict[str, object]],
    *,
    check_id: str,
    status: str,
    message: str,
    details: dict[str, object] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "status": status,
            "message": message,
            "details": details or {},
        }
    )


def run_doctor(
    config_path: Path,
    *,
    project_root: Path,
) -> dict[str, object]:
    del project_root
    checks: list[dict[str, object]] = []
    try:
        config = load_config(config_path)
    except Exception as exc:
        return {
            "schema": DOCTOR_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "error",
            "tools": list(PUBLIC_MCP_TOOLS),
            "checks": [
                {
                    "id": "config",
                    "status": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "details": {},
                }
            ],
        }
    _check(
        checks,
        check_id="config",
        status="ok",
        message="configuration loaded",
        details={"path": str(config_path)},
    )
    _memory_checks(config, checks)

    statuses = {str(item["status"]) for item in checks}
    overall = (
        "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    )
    return {
        "schema": DOCTOR_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": overall,
        "tools": list(PUBLIC_MCP_TOOLS),
        "checks": checks,
    }


def _memory_checks(config: KeepygagaConfig, checks: list[dict[str, object]]) -> None:
    if not config.memory.root.strip():
        _check(
            checks,
            check_id="memory_tree",
            status="warning",
            message="memory.root is not configured",
        )
        return
    root = Path(config.memory.root).expanduser().resolve()
    inspected = MemoryStore(root, config.memory).inspect()
    status = inspected.get("status")
    if status != "ok":
        _check(
            checks,
            check_id="memory_tree",
            status="warning" if status == "not_initialized" else "error",
            message=str(inspected.get("message", "memory tree is invalid")),
            details={"root": str(root), "source_status": status},
        )
        return
    split_recommended = inspected.get("split_recommended") is True
    raw_page_limit_exceeded = inspected.get("dynamic_page_limit_exceeded")
    dynamic_page_limit_exceeded = (
        raw_page_limit_exceeded if isinstance(raw_page_limit_exceeded, dict) else {}
    )
    exceeded_scopes = [
        str(scope)
        for scope, exceeded in dynamic_page_limit_exceeded.items()
        if exceeded is True
    ]
    permission_warnings = inspected.get("permission_warnings") or []
    if not isinstance(permission_warnings, list):
        permission_warnings = []
    warning = bool(split_recommended or exceeded_scopes or permission_warnings)
    if exceeded_scopes:
        message = (
            "memory tree is valid; page count exceeds the create limit for: "
            + ", ".join(exceeded_scopes)
        )
    elif permission_warnings:
        message = "memory tree is valid; one or more paths are more readable than the private default"
    elif split_recommended:
        message = "memory tree is valid; one or more pages should be split"
    else:
        message = "memory tree is valid"
    _check(
        checks,
        check_id="memory_tree",
        status="warning" if warning else "ok",
        message=message,
        details={
            "root": str(root),
            "capacities": inspected.get("capacities", {}),
            "split_recommended": split_recommended,
            "dynamic_pages": inspected.get("dynamic_pages", 0),
            "max_dynamic_pages": inspected.get("max_dynamic_pages"),
            "dynamic_page_limit_exceeded": dynamic_page_limit_exceeded,
            "permission_warnings": permission_warnings,
        },
    )
