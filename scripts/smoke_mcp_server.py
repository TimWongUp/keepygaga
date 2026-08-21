#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from keepygaga.config import MemoryFilesConfig
from keepygaga.diagnostics import run_doctor
from keepygaga.memory import initialize_memory_tree

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_TOOLS = {
    "list",
    "read",
    "create",
    "add",
    "update",
    "move",
    "rename",
    "delete",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查 Keepygaga stdio、八个 raw Tool 契约与只读 Doctor。"
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def _payload(result: Any) -> dict[str, object]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        if isinstance(structured.get("result"), dict):
            return structured["result"]
        return structured
    for block in result.content:
        if getattr(block, "type", "") == "text":
            value = json.loads(block.text)
            if isinstance(value, dict):
                return value
    raise RuntimeError("MCP tool did not return a JSON object")


async def run_smoke(timeout: float) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="keepygaga-smoke-") as directory:
        workspace = Path(directory)
        memory_root = workspace / "memory"
        initialized = initialize_memory_tree(
            memory_root,
            MemoryFilesConfig(root=str(memory_root)),
        )
        if initialized["status"] != "applied":
            raise RuntimeError(f"memory fixture failed: {initialized}")
        config_path = workspace / "keepygaga.toml"
        config_path.write_text(
            f"""
[memory]
root = "{memory_root}"
""".strip()
            + "\n",
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["KEEPYGAGA_CONFIG"] = str(config_path)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "mcp_server.py")],
            cwd=ROOT,
            env=environment,
        )
        async with asyncio.timeout(timeout):
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized_server = await session.initialize()
                    listed = await session.list_tools()
                    tool_names = sorted(tool.name for tool in listed.tools)
                    catalog = _payload(
                        await session.call_tool(
                            "list",
                            {},
                        )
                    )
                    read = _payload(
                        await session.call_tool(
                            "read",
                            {"paths": ["preferences.md"]},
                        )
                    )
                    files = read.get("files")
                    if not isinstance(files, list) or not files:
                        raise RuntimeError(f"memory read failed: {read}")
                    first = files[0]
                    if not isinstance(first, dict) or not isinstance(
                        first.get("version"), str
                    ):
                        raise RuntimeError(f"memory read has no version: {read}")
                    added = _payload(
                        await session.call_tool(
                            "add",
                            {
                                "operations": [
                                    {
                                        "path": "preferences.md",
                                        "if_version": first["version"],
                                        "facts": [
                                            {
                                                "basis": "stated",
                                                "content": (
                                                    "Temporary smoke-test memory."
                                                ),
                                            }
                                        ],
                                    }
                                ]
                            },
                        )
                    )
                    added_files = added.get("files")
                    if not isinstance(added_files, list) or not added_files:
                        raise RuntimeError(f"memory add failed: {added}")
                    updated = _payload(
                        await session.call_tool(
                            "update",
                            {
                                "operations": [
                                    {
                                        "path": "preferences.md",
                                        "if_version": added_files[0]["version"],
                                        "target": "fact",
                                        "old_fact": {
                                            "basis": "stated",
                                            "content": (
                                                "Temporary smoke-test memory."
                                            ),
                                        },
                                        "new_fact": {
                                            "basis": "stated",
                                            "content": (
                                                "Temporary smoke-test memory "
                                                "updated."
                                            ),
                                        },
                                    }
                                ]
                            },
                        )
                    )
        doctor = run_doctor(config_path, project_root=ROOT)
        status = (
            "ok"
            if set(tool_names) == REQUIRED_TOOLS
            and catalog.get("status") == "ok"
            and read.get("status") == "ok"
            and added.get("status") == "applied"
            and updated.get("status") == "applied"
            and doctor.get("status") in {"ok", "warning"}
            else "error"
        )
        return {
            "schema": "keepygaga-mcp-smoke-v4",
            "status": status,
            "server": initialized_server.serverInfo.name,
            "protocol_version": initialized_server.protocolVersion,
            "tool_count": len(tool_names),
            "tools": tool_names,
            "memory_status": updated.get("status"),
            "doctor_status": doctor.get("status"),
        }


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(run_smoke(args.timeout))
    except Exception as exc:
        report = {
            "schema": "keepygaga-mcp-smoke-v4",
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
