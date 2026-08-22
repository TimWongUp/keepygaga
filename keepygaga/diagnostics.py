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
DOCTOR_SCHEMA = "keepygaga-doctor-v6"


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
    _check(
        checks,
        check_id="memory_tree",
        status="warning" if split_recommended else "ok",
        message=(
            "memory tree is valid; one or more pages should be split"
            if split_recommended
            else "memory tree is valid"
        ),
        details={
            "root": str(root),
            "capacities": inspected.get("capacities", {}),
            "split_recommended": split_recommended,
        },
    )
