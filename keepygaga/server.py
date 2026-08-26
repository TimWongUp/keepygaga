from __future__ import annotations

from collections.abc import Callable
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


mcp = StrictFastMCP("Keepygaga")


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


@mcp.tool(name="list", annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def list_memory() -> dict[str, object]:
    """List the live route catalog: canonical paths, descriptions, and aliases."""
    return _with_memory_store(MemoryStore.list_files)


@mcp.tool(name="read", annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def read_memory(paths: ReadPaths) -> dict[str, object]:
    """Read listed canonical pages; returns Facts, opaque write versions, and capacity signals."""
    return _with_memory_store(lambda store: store.read(paths))


@mcp.tool(name="create", annotations=ToolAnnotations(readOnlyHint=False))
def create_pages(operations: CreateOperations) -> dict[str, object]:
    """Create dynamic pages after full-batch validation; applied results include Page Snapshots and receipts."""
    return _with_memory_store(lambda store: store.create(operations))


@mcp.tool(name="add", annotations=ToolAnnotations(readOnlyHint=False))
def add_facts(operations: AddOperations) -> dict[str, object]:
    """Add independent Facts using each page's latest Page Snapshot; applied results include current Page Snapshots and receipts."""
    return _with_memory_store(lambda store: store.add(operations))


@mcp.tool(name="update", annotations=ToolAnnotations(readOnlyHint=False))
def update_memory(operations: UpdateOperations) -> dict[str, object]:
    """Replace an exact Fact or page metadata; applied results include current Page Snapshots and receipts."""
    return _with_memory_store(lambda store: store.update(operations))


@mcp.tool(name="move", annotations=ToolAnnotations(readOnlyHint=False))
def move_fact(operations: MoveOperations) -> dict[str, object]:
    """Move exact Facts using both latest Page Snapshots; applied results include current Page Snapshots and receipts."""
    return _with_memory_store(lambda store: store.move(operations))


@mcp.tool(name="rename", annotations=ToolAnnotations(readOnlyHint=False))
def rename_page(operations: RenameOperations) -> dict[str, object]:
    """Rename dynamic pages using latest Page Snapshots; applied results include current Page Snapshots and receipts."""
    return _with_memory_store(lambda store: store.rename(operations))


@mcp.tool(name="delete", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
def delete_memory(operations: DeleteOperations) -> dict[str, object]:
    """Delete exact Facts or dynamic pages after explicit current-turn user authorization; applied results include surviving Page Snapshots and receipts."""
    return _with_memory_store(lambda store: store.delete(operations))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
