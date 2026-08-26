from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from keepygaga import server as mcp_server

EXPECTED_TOOLS = {
    "list",
    "read",
    "create",
    "add",
    "update",
    "move",
    "rename",
    "delete",
}

OPERATION_FIELDS = {
    "create": {"path", "description", "aliases", "facts"},
    "add": {"path", "if_version", "facts"},
    "move": {
        "source_path",
        "source_version",
        "destination_path",
        "destination_version",
        "fact",
    },
    "rename": {"path", "if_version", "new_path"},
}


def test_public_mcp_surface_and_exact_top_level_shapes() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == EXPECTED_TOOLS
    for tool in tools:
        assert tool.inputSchema["additionalProperties"] is False
    assert by_name["list"].inputSchema["properties"] == {}
    assert set(by_name["read"].inputSchema["properties"]) == {"paths"}
    assert by_name["read"].inputSchema["required"] == ["paths"]
    assert by_name["read"].inputSchema["properties"]["paths"]["minItems"] == 1
    assert by_name["read"].inputSchema["properties"]["paths"]["maxItems"] == 20

    for tool_name, expected_fields in OPERATION_FIELDS.items():
        schema = by_name[tool_name].inputSchema
        assert set(schema["properties"]) == {"operations"}
        assert schema["required"] == ["operations"]
        assert schema["properties"]["operations"]["minItems"] == 1
        assert schema["properties"]["operations"]["maxItems"] == 20
        reference = schema["properties"]["operations"]["items"]["$ref"]
        definition = schema["$defs"][reference.rsplit("/", 1)[-1]]
        assert set(definition["properties"]) == expected_fields
        assert definition["additionalProperties"] is False

    create_schema = by_name["create"].inputSchema
    create = create_schema["$defs"]["CreateOperation"]
    assert set(create["required"]) == {"path", "description", "aliases", "facts"}
    assert create["properties"]["aliases"]["maxItems"] == 8
    assert "minItems" not in create["properties"]["facts"]
    assert create["properties"]["facts"]["maxItems"] == 50
    fact_schema = create_schema["$defs"]["Fact"]
    assert set(fact_schema["properties"]) == {"basis", "content"}
    assert fact_schema["properties"]["basis"]["enum"] == ["stated", "observed"]
    fact_content = fact_schema["properties"]["content"]
    assert fact_content["maxLength"] == 4096
    descriptions = "".join(tool.description or "" for tool in tools)
    assert len(descriptions) < 1600
    assert "sources" not in descriptions.lower()
    assert "legacy" not in descriptions.lower()

    update_schema = by_name["update"].inputSchema
    update_items = update_schema["properties"]["operations"]["items"]
    assert update_items["discriminator"]["propertyName"] == "target"
    update_definitions = {
        reference["$ref"].rsplit("/", 1)[-1]
        for reference in update_items["oneOf"]
    }
    assert update_definitions == {"UpdateFactOperation", "UpdatePageOperation"}
    update_fact = update_schema["$defs"]["UpdateFactOperation"]
    update_page = update_schema["$defs"]["UpdatePageOperation"]
    assert set(update_fact["properties"]) == {
        "path",
        "if_version",
        "target",
        "old_fact",
        "new_fact",
    }
    assert set(update_page["properties"]) == {
        "path",
        "if_version",
        "target",
        "description",
        "aliases",
    }
    assert update_fact["additionalProperties"] is False
    assert update_page["additionalProperties"] is False
    assert update_fact["properties"]["target"]["const"] == "fact"
    assert update_page["properties"]["target"]["const"] == "page"
    assert set(update_fact["required"]) == {
        "path",
        "if_version",
        "target",
        "old_fact",
        "new_fact",
    }
    assert set(update_page["required"]) == {"path", "if_version", "target"}

    delete_schema = by_name["delete"].inputSchema
    delete_items = delete_schema["properties"]["operations"]["items"]
    assert delete_items["discriminator"]["propertyName"] == "target"
    delete_definitions = {
        reference["$ref"].rsplit("/", 1)[-1]
        for reference in delete_items["oneOf"]
    }
    assert delete_definitions == {"DeleteFactOperation", "DeletePageOperation"}
    delete_fact = delete_schema["$defs"]["DeleteFactOperation"]
    delete_page = delete_schema["$defs"]["DeletePageOperation"]
    assert set(delete_fact["properties"]) == {
        "path",
        "if_version",
        "target",
        "fact",
        "authorization",
    }
    assert set(delete_page["properties"]) == {
        "path",
        "if_version",
        "target",
        "authorization",
    }
    assert delete_fact["additionalProperties"] is False
    assert delete_page["additionalProperties"] is False
    assert delete_fact["properties"]["authorization"]["const"] == "user_requested"
    assert delete_fact["properties"]["target"]["const"] == "fact"
    assert delete_page["properties"]["target"]["const"] == "page"


def test_tool_protocol_is_discoverable_from_descriptions_and_schema() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert "live route catalog" in (by_name["list"].description or "")
    assert "opaque write versions" in (by_name["read"].description or "")
    assert "explicit current-turn user authorization" in (
        by_name["delete"].description or ""
    )

    read_paths = by_name["read"].inputSchema["properties"]["paths"]
    assert read_paths["description"] == (
        "Unique canonical page paths from the current Route Catalog."
    )

    add_schema = by_name["add"].inputSchema
    add = add_schema["$defs"]["AddOperation"]
    assert "latest Page Snapshot" in add["properties"]["if_version"]["description"]
    assert "exact duplicates only" in add["properties"]["facts"]["description"]
    assert "each path must be unique" in (
        add_schema["properties"]["operations"]["description"]
    )

    update_schema = by_name["update"].inputSchema
    update_fact = update_schema["$defs"]["UpdateFactOperation"]
    update_page = update_schema["$defs"]["UpdatePageOperation"]
    assert "Fact replacement" in update_fact["properties"]["target"]["description"]
    assert "cannot be downgraded" in (
        update_fact["properties"]["new_fact"]["description"]
    )
    assert "page description or aliases" in (
        update_page["properties"]["target"]["description"]
    )

    delete_schema = by_name["delete"].inputSchema
    delete_fact = delete_schema["$defs"]["DeleteFactOperation"]
    assert "current-turn user authorization" in (
        delete_fact["properties"]["authorization"]["description"]
    )

    for name in EXPECTED_TOOLS - {"list", "read"}:
        description = by_name[name].description or ""
        assert "Page Snapshots" in description
        assert "receipts" in description

    fact_schema = add_schema["$defs"]["Fact"]
    assert "explicit statement" in fact_schema["properties"]["basis"]["description"]
    assert "independently maintainable" in (
        fact_schema["properties"]["content"]["description"]
    )


def test_tool_annotations_match_read_and_destructive_behavior() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    for name in {"list", "read"}:
        annotations = by_name[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True
    for name in EXPECTED_TOOLS - {"list", "read"}:
        annotations = by_name[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is False
    delete_annotations = by_name["delete"].annotations
    assert delete_annotations is not None
    assert delete_annotations.destructiveHint is True


def test_update_discriminated_operations_are_rejected_at_model_boundary() -> None:
    update_tool = mcp_server.mcp._tool_manager.get_tool("update")
    assert update_tool is not None
    with pytest.raises(ValidationError):
        update_tool.fn_metadata.arg_model.model_validate(
            {
                "operations": [
                    {
                        "path": "topics/example.md",
                        "if_version": "opaque",
                        "target": "fact",
                        "old_fact": {"basis": "stated", "content": "Same."},
                        "new_fact": {"basis": "stated", "content": "Same."},
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        update_tool.fn_metadata.arg_model.model_validate(
            {
                "operations": [
                    {
                        "path": "topics/example.md",
                        "if_version": "opaque",
                        "target": "page",
                    }
                ]
            }
        )
    with pytest.raises(ValidationError):
        update_tool.fn_metadata.arg_model.model_validate(
            {
                "operations": [
                    {
                        "path": "topics/example.md",
                        "if_version": "opaque",
                        "target": "fact",
                        "old_fact": {"basis": "stated", "content": "Old."},
                        "new_fact": {"basis": "stated", "content": "New."},
                        "unexpected": True,
                    }
                ]
            }
        )


def test_runtime_rejects_unexpected_top_level_arguments() -> None:
    for tool in mcp_server.mcp._tool_manager.list_tools():
        with pytest.raises(ValidationError):
            tool.fn_metadata.arg_model.model_validate(
                {
                    **(
                        {"paths": ["profile.md"]}
                        if tool.name == "read"
                        else {}
                    ),
                    "unexpected": True,
                }
            )


def test_runtime_rejects_more_than_twenty_read_paths() -> None:
    tool = next(
        tool
        for tool in mcp_server.mcp._tool_manager.list_tools()
        if tool.name == "read"
    )
    with pytest.raises(ValidationError):
        tool.fn_metadata.arg_model.model_validate(
            {"paths": [f"topics/page-{index}.md" for index in range(21)]}
        )

def test_closed_schema_adapter_fails_closed_without_fastmcp_tool_manager() -> None:
    class EmptyServer:
        pass

    with pytest.raises(RuntimeError, match="closed-schema adapter"):
        mcp_server._close_registered_tool(EmptyServer(), "list")  # type: ignore[arg-type]

