from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

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
        tool_name = name or fn.__name__
        tool = self._tool_manager.get_tool(tool_name)
        if tool is None:  # pragma: no cover
            raise RuntimeError(f"tool registration failed: {tool_name}")
        arguments = tool.fn_metadata.arg_model
        arguments.model_config["extra"] = "forbid"
        arguments.model_rebuild(force=True)
        tool.parameters = arguments.model_json_schema(by_alias=True)

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
