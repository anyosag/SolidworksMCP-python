"""``set_dimension`` on a pattern's count and angle, on real SolidWorks.

From the Cellvis dish rack: setting a circular pattern's instance count to 2
wrote 0.002, and its 180-degree spacing 0.18 rad, so the pattern failed to
rebuild. Here a 3-hole pattern, 60 degrees apart, becomes 2 holes 180 degrees
apart through ``set_dimension`` alone, and the removed volume shows it.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_dimension_units.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.live.evidence import evidence
from tests.live.test_live_sw_pattern_visibility_delete import (
    _HOLE_R,
    _THICK,
    _disc_with_hole,
    _volume,
)


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.engineering_data import register_engineering_data_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("dimension-units-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_engineering_data_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


@pytest.mark.asyncio
async def test_a_pattern_count_and_angle_are_set_in_their_own_units(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    hole = await _disc_with_hole(tools)
    axis = await tools["create_axis"]({"reference": "y"})
    assert axis["status"] == "success", axis
    pattern = await tools["pattern_circular"](
        {"features": [hole], "axis": axis["axis"]["name"], "count": 3, "step_angle": 60}
    )
    assert pattern["status"] == "success", pattern
    name = pattern["pattern"]["name"]
    listed = await tools["list_model_dimensions"]({"feature_name": name})
    assert listed["status"] == "success", listed
    by_kind = {d["kind"]: d for d in listed["data"]}
    assert by_kind["count"]["units"] == "count"
    assert by_kind["angle"]["units"] == "deg"
    hole_volume = math.pi * _HOLE_R**2 * _THICK
    three_holes = await _volume(adapter)

    count = await tools["set_dimension"](
        {"name": by_kind["count"]["full_name"], "value": 2}
    )
    angle = await tools["set_dimension"](
        {"name": by_kind["angle"]["full_name"], "value": 180}
    )
    rebuilt = await tools["rebuild_model"]({})
    two_holes = await _volume(adapter)
    read = await tools["get_dimension"]({"name": by_kind["angle"]["full_name"]})

    evidence(
        "3 holes 60 degrees apart become 2 holes 180 apart through set_dimension",
        {
            "dimensions": listed["data"],
            "count": count["dimension_update"],
            "angle": angle["dimension_update"],
            "volume_change_mm3": two_holes - three_holes,
        },
    )
    assert count["status"] == "success", count
    assert count["dimension_update"]["new_value"] == 2
    assert angle["status"] == "success", angle
    assert angle["dimension_update"]["new_value"] == pytest.approx(180)
    assert rebuilt["status"] == "success", rebuilt
    assert two_holes - three_holes == pytest.approx(hole_volume, rel=1e-3)
    assert read["dimension"]["value"] == pytest.approx(180)
    assert read["dimension"]["units"] == "deg"


@pytest.mark.asyncio
async def test_a_fractional_count_is_refused(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    hole = await _disc_with_hole(tools)
    axis = await tools["create_axis"]({"reference": "y"})
    pattern = await tools["pattern_circular"](
        {"features": [hole], "axis": axis["axis"]["name"], "count": 3, "step_angle": 60}
    )
    listed = await tools["list_model_dimensions"](
        {"feature_name": pattern["pattern"]["name"]}
    )
    count = next(d for d in listed["data"] if d["kind"] == "count")

    result = await tools["set_dimension"]({"name": count["full_name"], "value": 2.5})

    evidence("count 2.5 is refused", result)
    assert result["status"] == "error"
    assert "give a whole number" in result["message"]
