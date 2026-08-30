from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.types import AnyFunction, Icon, ToolAnnotations

from keepygaga.config import load_config
from keepygaga.memory import (
    AddOperations,
    CreateOperations,
    DeleteOperations,
    MemoryStore,
    MoveOperations,
    ReadPaths,
    RenameOperations,
    UpdateOperations,
)

COMPATIBLE_MCP_NOTE = "compatible with MCP SDK 1.12-1.28 closed-schema adapter"
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
ADDITIVE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
MUTATING_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


def _close_registered_tool(server: FastMCP, tool_name: str) -> None:
    manager = getattr(server, "_tool_manager", None)
    get_tool = getattr(manager, "get_tool", None)
    if not callable(get_tool):
        raise RuntimeError(
            f"FastMCP closed-schema adapter cannot find {tool_name}; {COMPATIBLE_MCP_NOTE}"
        )
    tool = get_tool(tool_name)
    if tool is None:
        raise RuntimeError(f"tool registration failed: {tool_name}")
    fn_metadata = getattr(tool, "fn_metadata", None)
    arguments = getattr(fn_metadata, "arg_model", None)
    config = getattr(arguments, "model_config", None)
    rebuild = getattr(arguments, "model_rebuild", None)
    schema = getattr(arguments, "model_json_schema", None)
    if not isinstance(config, dict) or not callable(rebuild) or not callable(schema):
        raise RuntimeError(
            f"FastMCP closed-schema adapter cannot close {tool_name}; {COMPATIBLE_MCP_NOTE}"
        )
    config["extra"] = "forbid"
    rebuild(force=True)
    generated = schema(by_alias=True)
    if not isinstance(generated, dict):
        raise RuntimeError(
            f"FastMCP closed-schema adapter cannot publish {tool_name}; {COMPATIBLE_MCP_NOTE}"
        )
    try:
        cast(Any, tool).parameters = generated
    except Exception as exc:
        raise RuntimeError(
            f"FastMCP closed-schema adapter cannot publish {tool_name}; {COMPATIBLE_MCP_NOTE}"
        ) from exc


class StrictFastMCP(FastMCP):
    """FastMCP with closed top-level argument models."""

    def add_tool(
        self,
        fn: AnyFunction,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> None:
        super().add_tool(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )
        _close_registered_tool(self, name or fn.__name__)



def _server_instructions() -> str:
    return files("keepygaga").joinpath("mcp_instructions.md").read_text(encoding="utf-8")


mcp = StrictFastMCP("Keepygaga", instructions=_server_instructions())


def _with_memory_store(
    operation: Callable[[MemoryStore], dict[str, object]],
) -> dict[str, object]:
    try:
        config = load_config()
    except Exception as exc:
        return {
            "status": "invalid_source",
            "message": f"configuration could not be loaded: {exc}",
        }
    if not config.memory.root.strip():
        return {
            "status": "not_initialized",
            "message": "memory.root is not configured",
        }
    store = MemoryStore(Path(config.memory.root), config.memory)
    return operation(store)


@mcp.tool(name="list", annotations=READ_ONLY_ANNOTATIONS)
def list_memory() -> dict[str, object]:
    """Use when the current Route Catalog is missing or stale. Returns live canonical page paths, descriptions, and aliases; it does not return Facts or write versions."""
    return _with_memory_store(MemoryStore.list_files)


@mcp.tool(name="read", annotations=READ_ONLY_ANNOTATIONS)
def read_memory(paths: ReadPaths) -> dict[str, object]:
    """Use before mutation unless current Page Snapshots are already available. Read unique canonical paths together; returned files contain Facts, opaque write versions, and capacity signals."""
    return _with_memory_store(lambda store: store.read(paths))


@mcp.tool(name="create", annotations=ADDITIVE_ANNOTATIONS)
def create_pages(operations: CreateOperations) -> dict[str, object]:
    """Create new dynamic pages after full-batch validation. On applied, reuse returned Page Snapshots and receipts; do not call read or list solely to verify success."""
    return _with_memory_store(lambda store: store.create(operations))


@mcp.tool(name="add", annotations=ADDITIVE_ANNOTATIONS)
def add_facts(operations: AddOperations) -> dict[str, object]:
    """Add independent Facts using each page's latest Page Snapshot. Group Facts for one page in one operation. On applied, reuse returned Page Snapshots and receipts; do not verify with read or list."""
    return _with_memory_store(lambda store: store.add(operations))


@mcp.tool(name="update", annotations=MUTATING_ANNOTATIONS)
def update_memory(operations: UpdateOperations) -> dict[str, object]:
    """Replace an exact Fact or page metadata using the latest Page Snapshot. Use one operation per page. On applied, reuse returned Page Snapshots and receipts; do not verify with read or list."""
    return _with_memory_store(lambda store: store.update(operations))


@mcp.tool(name="move", annotations=MUTATING_ANNOTATIONS)
def move_fact(operations: MoveOperations) -> dict[str, object]:
    """Move one or more exact Facts between existing pages using both latest Page Snapshots. Put all Facts for one source/destination pair in one operation. On applied, reuse returned Page Snapshots and receipts; do not verify with read or list."""
    return _with_memory_store(lambda store: store.move(operations))


@mcp.tool(name="rename", annotations=MUTATING_ANNOTATIONS)
def rename_page(operations: RenameOperations) -> dict[str, object]:
    """Rename dynamic pages using latest Page Snapshots, one operation per page. On applied, reuse returned Page Snapshots and receipts; do not verify with read or list."""
    return _with_memory_store(lambda store: store.rename(operations))


@mcp.tool(name="delete", annotations=MUTATING_ANNOTATIONS)
def delete_memory(operations: DeleteOperations) -> dict[str, object]:
    """Delete exact Facts or dynamic pages only after explicit current-turn user authorization. On applied, reuse surviving Page Snapshots and receipts; do not verify with read or list."""
    return _with_memory_store(lambda store: store.delete(operations))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
