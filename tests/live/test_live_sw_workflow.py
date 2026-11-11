"""``execute_workflow`` on real SolidWorks: a block in one call, and a rollback.

From the Cellvis dish-rack session's suggestions: a batch tool that runs a
list of steps, stops at the first error, and can roll back.

- the four steps of a 40 x 30 x 10 mm block run in one call and make
  12000 mm³;
- the same steps followed by a step that fails, with ``rollback_on_error``,
  leave the part's tree as it was before the call.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_workflow.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.live.evidence import evidence

_BLOCK = [
    {"tool": "create_sketch", "arguments": {"plane": "Top"}},
    {"tool": "add_rectangle", "arguments": {"x1": -20, "y1": -15, "x2": 20, "y2": 15}},
    {"tool": "exit_sketch"},
    {"tool": "create_extrusion", "arguments": {"depth": 10}},
]


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.automation import register_automation_tools
    from solidworks_mcp.tools.file_management import register_file_management_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("workflow-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_file_management_tools(mcp, adapter, {})
    await register_automation_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _volume(adapter: Any) -> float:
    result = await adapter.get_model_geometry_summary()
    assert result.is_success, result.error
    return float(result.data["volume_mm3"])


@pytest.mark.asyncio
async def test_a_block_in_one_call(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success

    result = await tools["execute_workflow"](
        {"workflow_name": "block", "steps": _BLOCK}
    )
    volume = await _volume(adapter)

    evidence("4 steps in one execute_workflow call (expect 12000 mm³)", volume)
    assert result["status"] == "success", result
    assert result["completed"] == 4
    assert volume == pytest.approx(12000, rel=1e-4)


@pytest.mark.asyncio
async def test_a_failing_step_rolls_the_part_back(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    before = [f["name"] for f in (await tools["list_features"]({}))["features"]]
    failing = {"tool": "select_edges", "arguments": {"feature": "NoSuchFeature"}}

    result = await tools["execute_workflow"](
        {"steps": [*_BLOCK, failing], "rollback_on_error": True}
    )
    after = [f["name"] for f in (await tools["list_features"]({}))["features"]]

    evidence("block then a failing step, rolled back", result.get("data"))
    assert result["status"] == "error"
    assert result["data"]["failed_step"] == 4
    assert result["data"]["rolled_back"]["done"] is True
    assert after == before
