from __future__ import annotations

import asyncio

from mcp import Client

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
    "add": {"path", "if_version", "description", "facts"},
    "move": {
        "source_path",
        "source_version",
        "destination_path",
        "destination_version",
        "new_path",
        "description",
        "aliases",
        "source_description",
        "facts",
    },
    "rename": {"path", "if_version", "new_path"},
}


def test_public_mcp_surface_and_exact_top_level_shapes() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == EXPECTED_TOOLS
    for tool in tools:
        assert tool.input_schema["additionalProperties"] is False
    list_schema = by_name["list"].input_schema
    assert set(list_schema["properties"]) == {"scope"}
    assert list_schema["required"] == ["scope"]
    assert list_schema["properties"]["scope"]["enum"] == [
        "topics",
        "areas",
        "people",
    ]
    assert set(by_name["read"].input_schema["properties"]) == {"paths"}
    assert by_name["read"].input_schema["required"] == ["paths"]
    assert by_name["read"].input_schema["properties"]["paths"]["minItems"] == 1
    assert by_name["read"].input_schema["properties"]["paths"]["maxItems"] == 15

    for tool_name, expected_fields in OPERATION_FIELDS.items():
        schema = by_name[tool_name].input_schema
        assert set(schema["properties"]) == {"operations"}
        assert schema["required"] == ["operations"]
        assert schema["properties"]["operations"]["minItems"] == 1
        assert schema["properties"]["operations"]["maxItems"] == 15
        reference = schema["properties"]["operations"]["items"]["$ref"]
        definition = schema["$defs"][reference.rsplit("/", 1)[-1]]
        assert set(definition["properties"]) == expected_fields
        assert definition["additionalProperties"] is False

    create_schema = by_name["create"].input_schema
    create = create_schema["$defs"]["CreateOperation"]
    assert set(create["required"]) == {"path", "description", "aliases", "facts"}
    assert create["properties"]["description"]["maxLength"] == 80
    assert create["properties"]["aliases"]["maxItems"] == 6
    assert "minItems" not in create["properties"]["facts"]
    assert create["properties"]["facts"]["maxItems"] == 30
    fact_schema = create_schema["$defs"]["Fact"]
    assert set(fact_schema["properties"]) == {"basis", "content"}
    assert fact_schema["properties"]["basis"]["enum"] == ["stated", "observed"]
    fact_content = fact_schema["properties"]["content"]
    assert fact_content["maxLength"] == 800
    descriptions = "".join(tool.description or "" for tool in tools)
    assert len(descriptions) < 2400
    assert "sources" not in descriptions.lower()
    assert "legacy" not in descriptions.lower()

    update_schema = by_name["update"].input_schema
    update_items = update_schema["properties"]["operations"]["items"]
    assert update_items["discriminator"]["propertyName"] == "target"
    update_definitions = {
        reference["$ref"].rsplit("/", 1)[-1] for reference in update_items["oneOf"]
    }
    assert update_definitions == {
        "UpdateFactOperation",
        "UpdatePageOperation",
        "RepairPageOperation",
    }
    update_fact = update_schema["$defs"]["UpdateFactOperation"]
    update_page = update_schema["$defs"]["UpdatePageOperation"]
    repair_page = update_schema["$defs"]["RepairPageOperation"]
    assert set(update_fact["properties"]) == {
        "path",
        "if_version",
        "target",
        "old_fact",
        "new_fact",
        "description",
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
    update_description = next(
        branch
        for branch in update_page["properties"]["description"]["anyOf"]
        if branch.get("type") == "string"
    )
    update_aliases = next(
        branch
        for branch in update_page["properties"]["aliases"]["anyOf"]
        if branch.get("type") == "array"
    )
    assert update_description["maxLength"] == 80
    assert update_aliases["maxItems"] == 6
    update_fact_description = next(
        branch
        for branch in update_fact["properties"]["description"]["anyOf"]
        if branch.get("type") == "string"
    )
    assert update_fact_description["maxLength"] == 80
    assert set(update_fact["required"]) == {
        "path",
        "if_version",
        "target",
        "old_fact",
        "new_fact",
    }
    assert set(update_page["required"]) == {"path", "if_version", "target"}
    assert set(repair_page["properties"]) == {"path", "if_version", "target"}
    assert repair_page["properties"]["target"]["const"] == "repair"

    delete_schema = by_name["delete"].input_schema
    delete_items = delete_schema["properties"]["operations"]["items"]
    assert delete_items["discriminator"]["propertyName"] == "target"
    delete_definitions = {
        reference["$ref"].rsplit("/", 1)[-1] for reference in delete_items["oneOf"]
    }
    assert delete_definitions == {"DeleteFactOperation", "DeletePageOperation"}
    delete_fact = delete_schema["$defs"]["DeleteFactOperation"]
    delete_page = delete_schema["$defs"]["DeletePageOperation"]
    assert set(delete_fact["properties"]) == {
        "path",
        "if_version",
        "target",
        "fact",
        "description",
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
    instructions = mcp_server._server_instructions()

    assert "`areas/projects.md`" in instructions
    assert "exactly one Fact per maintained project" in instructions
    assert "<https://github.com/owner/repo>" in instructions
    assert "use `create` with the initial project Fact" in instructions
    assert "do not create a duplicate canonical page" in instructions
    assert "must use `update`" in instructions

    assert "Route Catalog" in (by_name["list"].description or "")
    assert "opaque write versions" in (by_name["read"].description or "")
    assert "explicit current-turn user authorization" in (
        by_name["delete"].description or ""
    )

    read_paths = by_name["read"].input_schema["properties"]["paths"]
    assert read_paths["description"] == (
        "Unique canonical page paths from the current Route Catalog."
    )

    add_schema = by_name["add"].input_schema
    add = add_schema["$defs"]["AddOperation"]
    assert "latest Page Snapshot" in add["properties"]["if_version"]["description"]
    assert "exact duplicates only" in add["properties"]["facts"]["description"]
    assert add["properties"]["facts"]["maxItems"] == 30
    add_description = next(
        branch
        for branch in add["properties"]["description"]["anyOf"]
        if branch.get("type") == "string"
    )
    assert add_description["maxLength"] == 80
    assert (
        "each path must be unique"
        in (add_schema["properties"]["operations"]["description"])
    )

    move_schema = by_name["move"].input_schema
    move = move_schema["$defs"]["MoveOperation"]
    assert len(move["oneOf"]) == 2
    assert move["oneOf"][0]["required"] == [
        "destination_path",
        "destination_version",
    ]
    assert move["oneOf"][1]["required"] == ["new_path", "description", "aliases"]
    assert "description" not in move["oneOf"][0]["properties"]
    assert move["oneOf"][0]["properties"]["aliases"] == {"type": "null"}
    assert move["properties"]["facts"]["minItems"] == 1
    assert move["properties"]["facts"]["maxItems"] == 30
    move_description = next(
        branch
        for branch in move["properties"]["description"]["anyOf"]
        if branch.get("type") == "string"
    )
    move_aliases = next(
        branch
        for branch in move["properties"]["aliases"]["anyOf"]
        if branch.get("type") == "array"
    )
    assert move_description["maxLength"] == 80
    assert move_aliases["maxItems"] == 6
    assert "new destination" in move["properties"]["aliases"]["description"]
    source_description = next(
        branch
        for branch in move["properties"]["source_description"]["anyOf"]
        if branch.get("type") == "string"
    )
    assert source_description["maxLength"] == 80
    selector_schema = move_schema["$defs"]["FactSelector"]
    assert set(selector_schema["properties"]) == {"basis", "content"}
    assert selector_schema["properties"]["content"]["maxLength"] == 4096
    assert (
        "all Facts for that pair"
        in (move_schema["properties"]["operations"]["description"])
    )
    assert "new destination" in (by_name["move"].description or "")

    update_schema = by_name["update"].input_schema
    update_fact = update_schema["$defs"]["UpdateFactOperation"]
    update_page = update_schema["$defs"]["UpdatePageOperation"]
    repair_page = update_schema["$defs"]["RepairPageOperation"]
    assert "Fact replacement" in update_fact["properties"]["target"]["description"]
    assert (
        "cannot be downgraded" in (update_fact["properties"]["new_fact"]["description"])
    )
    assert update_fact["properties"]["old_fact"]["$ref"].endswith("/FactSelector")
    assert update_fact["properties"]["new_fact"]["$ref"].endswith("/Fact")
    assert (
        "page description or aliases"
        in (update_page["properties"]["target"]["description"])
    )
    assert (
        "Mechanically canonicalize"
        in (repair_page["properties"]["target"]["description"])
    )

    delete_schema = by_name["delete"].input_schema
    delete_fact = delete_schema["$defs"]["DeleteFactOperation"]
    assert (
        "current-turn user authorization"
        in (delete_fact["properties"]["authorization"]["description"])
    )
    delete_description = next(
        branch
        for branch in delete_fact["properties"]["description"]["anyOf"]
        if branch.get("type") == "string"
    )
    assert delete_description["maxLength"] == 80

    for name in EXPECTED_TOOLS - {"list", "read"}:
        description = by_name[name].description or ""
        assert "Page Snapshots" in description
        assert "receipts" in description
        assert "read or list" in description

    fact_schema = add_schema["$defs"]["Fact"]
    assert "explicit statement" in fact_schema["properties"]["basis"]["description"]
    assert (
        "independently maintainable"
        in (fact_schema["properties"]["content"]["description"])
    )


def test_tool_annotations_match_read_and_destructive_behavior() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    for name in {"list", "read"}:
        annotations = by_name[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is False
        assert annotations.idempotent_hint is True
        assert annotations.open_world_hint is False
    for name in EXPECTED_TOOLS - {"list", "read"}:
        annotations = by_name[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.idempotent_hint is False
        assert annotations.open_world_hint is False
    create_annotations = by_name["create"].annotations
    assert create_annotations is not None
    assert create_annotations.destructive_hint is False
    for name in {"add", "update", "move", "rename", "delete"}:
        annotations = by_name[name].annotations
        assert annotations is not None
        assert annotations.destructive_hint is True


async def _call_tool(name: str, arguments: dict[str, object]):
    async with Client(mcp_server.mcp) as client:
        return await client.call_tool(name, arguments)


def test_update_discriminated_operations_are_rejected_at_public_boundary() -> None:
    for operation in (
        {
            "path": "topics/example.md",
            "if_version": "opaque",
            "target": "fact",
            "old_fact": {"basis": "stated", "content": "Same."},
            "new_fact": {"basis": "stated", "content": "Same."},
        },
        {
            "path": "topics/example.md",
            "if_version": "opaque",
            "target": "page",
        },
        {
            "path": "topics/example.md",
            "if_version": "opaque",
            "target": "fact",
            "old_fact": {"basis": "stated", "content": "Old."},
            "new_fact": {"basis": "stated", "content": "New."},
            "unexpected": True,
        },
    ):
        result = asyncio.run(_call_tool("update", {"operations": [operation]}))
        assert result.is_error is True


def test_move_destination_modes_are_rejected_when_partial_or_mixed() -> None:
    common = {
        "source_path": "topics/source.md",
        "source_version": "opaque",
        "facts": [{"basis": "stated", "content": "Move me."}],
    }
    for destination in (
        {"destination_path": "topics/destination.md"},
        {
            "destination_path": "topics/destination.md",
            "destination_version": "opaque",
            "aliases": [],
        },
        {
            "destination_path": "topics/destination.md",
            "destination_version": "opaque",
            "new_path": "topics/new.md",
            "description": "New page.",
            "aliases": [],
        },
    ):
        result = asyncio.run(
            _call_tool("move", {"operations": [{**common, **destination}]})
        )
        assert result.is_error is True


def test_runtime_rejects_unexpected_top_level_arguments() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    for tool in tools:
        arguments = {"paths": ["profile.md"]} if tool.name == "read" else {}
        result = asyncio.run(_call_tool(tool.name, {**arguments, "unexpected": True}))
        assert result.is_error is True


def test_runtime_rejects_more_than_fifteen_read_paths() -> None:
    result = asyncio.run(
        _call_tool(
            "read", {"paths": [f"topics/page-{index}.md" for index in range(16)]}
        )
    )
    assert result.is_error is True
