"""The ``document`` argument and the shared-document warning, on real SolidWorks.

From the Cellvis dish-rack session's suggestions: a session names the
document a call works on instead of calling ``activate_document`` first, and
hears when another MCP server is working on the same document.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_document_argument.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.file_management import register_file_management_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("document-argument-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_file_management_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _part(tools: dict[str, Any]) -> str:
    created = await tools["create_part"]({})
    assert created["status"] == "success", created
    info = await tools["get_model_info"]()
    return str(info["model_info"]["title"])


def _sketches(tree: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in tree["features"] if f["type"] == "ProfileFeature"]


@pytest.mark.asyncio
async def test_a_call_names_its_document(scratch) -> None:
    """A sketch drawn with ``document`` lands in that part, not the active one."""
    tools = await _tools(scratch.adapter)
    first = await _part(tools)
    second = await _part(tools)

    sketch = await tools["create_sketch"]({"plane": "Front"}, document=first)
    line = await tools["add_line"](
        {"x1": 0, "y1": 0, "x2": 10, "y2": 0}, document=first
    )
    closed = await tools["exit_sketch"](document=first)
    on_first = await tools["list_features"]({}, document=first)
    on_second = await tools["list_features"]({}, document=second)
    missing = await tools["list_features"]({}, document="NoSuchPart.SLDPRT")

    evidence(
        f"a sketch drawn with document={first!r} while {second!r} was active",
        {"sketch": sketch, "line": line, "missing": missing},
    )
    assert sketch["status"] == line["status"] == closed["status"] == "success"
    assert len(_sketches(on_first)) == 1
    assert _sketches(on_second) == []
    assert missing["error_type"] == "not_found"


@pytest.mark.asyncio
async def test_another_server_on_the_same_document_is_named(scratch) -> None:
    """A register entry for another live process on this document gives a warning."""
    from solidworks_mcp.adapters.solidworks.sessions import SessionRegister

    adapter = scratch.adapter
    tools = await _tools(adapter)
    first = await _part(tools)
    await _part(tools)
    # The test runner's parent process stands in for a second MCP server.
    other = SessionRegister(adapter._sessions.directory, pid=os.getppid())
    other.record(adapter._sw_process_id, ("", first))
    try:
        reply = await tools["get_model_info"](document=first)
    finally:
        other.forget()

    evidence(f"another server on {first!r}", reply)
    assert reply["status"] == "success", reply
    assert f"process {os.getppid()}) is also working on '{first}'" in reply["warning"]
