from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Tool as MCPTool
from mcp.types import ToolAnnotations

from keepygaga.config import load_config
from keepygaga.memory import (
    AddOperations,
    CreateOperations,
    DeleteOperations,
    MemoryScope,
    MemoryStore,
    MoveOperations,
    ReadPaths,
    RenameOperations,
    UpdateOperations,
)

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
ADDITIVE_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
MUTATING_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


class StrictMCPServer(MCPServer):
    """Expose closed top-level input schemas and enforce them at call time.

    MCPServer's generated argument models intentionally accept unknown fields for
    compatibility. Keepygaga's public contract is closed, so this small public
    boundary adapter publishes a copied schema with ``additionalProperties``
    disabled and rejects unknown top-level keys before dispatch.
    """

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        closed: list[MCPTool] = []
        for tool in tools:
            schema = deepcopy(tool.input_schema)
            schema["additionalProperties"] = False
            closed.append(tool.model_copy(update={"input_schema": schema}))
        return closed

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any = None,
    ) -> Any:
        tools = await self.list_tools()
        tool = next((candidate for candidate in tools if candidate.name == name), None)
        if tool is not None:
            properties = tool.input_schema.get("properties", {})
            if isinstance(properties, dict):
                unexpected = sorted(set(arguments) - set(properties))
                if unexpected:
                    joined = ", ".join(unexpected)
                    raise ToolError(
                        f"Error executing tool {name}: unexpected top-level argument(s): {joined}"
                    )
        return await super().call_tool(name, arguments, context)


def _server_instructions() -> str:
    return (
        files("keepygaga").joinpath("mcp_instructions.md").read_text(encoding="utf-8")
    )


mcp = StrictMCPServer("Keepygaga", instructions=_server_instructions())


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
def list_memory(scope: MemoryScope) -> dict[str, object]:
    """Return one complete live topics, areas, or people Route Catalog. No search, matching, pagination, Facts, or write versions."""
    return _with_memory_store(lambda store: store.list_files(scope))


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
    """Replace an exact Fact, update page metadata, or mechanically repair a repairable page using its latest version. On applied, reuse returned Page Snapshots and receipts; do not verify with read or list."""
    return _with_memory_store(lambda store: store.update(operations))


@mcp.tool(name="move", annotations=MUTATING_ANNOTATIONS)
def move_fact(operations: MoveOperations) -> dict[str, object]:
    """Move exact Facts to an existing page or atomically create a bounded new destination. Preserve Fact dates and leave at least one source Fact. On applied, reuse returned Page Snapshots and receipts; do not verify with read or list."""
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
