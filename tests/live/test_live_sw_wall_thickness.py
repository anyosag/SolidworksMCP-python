"""``check_wall_thickness`` on real SolidWorks: a pocket that leaves a 1 mm floor.

From the Cellvis dish-rack session: a 3D-printed part needs a check for
walls the printer can't make. A 40 x 30 x 5 mm plate gets a 20 x 10 mm
pocket 4 mm deep from the top, leaving a 1 mm floor:

- the thinnest wall measured is the floor, 1 mm (within 0.05 mm), and it is
  found under the pocket;
- with ``min_wall_mm: 1.2`` the floor is listed as too thin; with 0.8 the
  part passes.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_wall_thickness.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.analysis import register_analysis_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("wall-thickness-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_analysis_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _plate_with_pocket(adapter: Any, tools: dict[str, Any]) -> None:
    assert (await adapter.create_part()).is_success
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    plate = {"x1": -20, "y1": -15, "x2": 20, "y2": 15}
    assert (await tools["add_rectangle"](plate))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    boss = await tools["create_extrusion"]({"depth": 5.0})
    assert boss["status"] == "success", boss

    top = await tools["create_reference_plane"](
        {"reference": "Top Plane", "offset": 5.0}
    )
    assert top["status"] == "success", top
    sketch = await tools["create_sketch"]({"plane": top["plane"]["name"]})
    assert sketch["status"] == "success", sketch
    pocket = {"x1": -10, "y1": -5, "x2": 10, "y2": 5}
    assert (await tools["add_rectangle"](pocket))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    cut = await tools["create_cut_extrude"]({"depth": 4.0})
    assert cut["status"] == "success", cut


@pytest.mark.asyncio
async def test_the_pocket_floor_is_the_thinnest_wall(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _plate_with_pocket(adapter, tools)

    strict = await tools["check_wall_thickness"]({"min_wall_mm": 1.2})
    relaxed = await tools["check_wall_thickness"]({"min_wall_mm": 0.8})

    evidence("a 1 mm pocket floor, checked at 1.2 and 0.8 mm", strict.get("data"))
    assert strict["status"] == "success", strict
    data = strict["data"]
    assert data["min_thickness_mm"] == pytest.approx(1.0, abs=0.05)
    # Under the pocket, on its floor (y = 1) or on the plate's bottom (y = 0).
    x, y, z = data["at_mm"]
    assert -10 <= x <= 10
    assert -5 <= z <= 5
    assert min(abs(y - 1.0), abs(y)) < 0.05
    assert data["below_minimum"] > 0
    assert data["ok"] is False
    assert relaxed["data"]["ok"] is True
