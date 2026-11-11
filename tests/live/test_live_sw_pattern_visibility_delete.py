"""Pattern step angles, show/hide and absorbed sketches on real SolidWorks.

From the Cellvis dish-rack session's suggestions:

- ``pattern_circular`` with ``step_angle: 60`` puts 3 holes 60 degrees apart
  (it needed ``angle: 300`` with ``equal_spacing: false`` before), and
  ``reverse_direction`` puts them on the other side;
- ``set_visibility`` hides every plane and puts them back, and hides one
  plane and one sketch by name;
- ``delete_feature`` on a cut names the sketch it leaves, and
  ``delete_absorbed`` removes it too.

Run one with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_pattern_visibility_delete.py::test_step_angle_puts_holes_sixty_degrees_apart

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.live.evidence import evidence

_HOLE_R, _HOLE_AT, _THICK = 3.0, 20.0, 5.0


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.file_management import register_file_management_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("pattern-visibility-delete-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_file_management_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _volume(adapter: Any) -> float:
    result = await adapter.get_model_geometry_summary()
    assert result.is_success, result.error
    return float(result.data["volume_mm3"])


async def _disc_with_hole(tools: dict[str, Any]) -> str:
    """A 60 mm disc, 5 mm thick, with one 6 mm hole 20 mm out on sketch x."""

    async def _circle(center_x: float, radius: float) -> None:
        assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
        circle = {"center_x": center_x, "center_y": 0, "radius": radius}
        assert (await tools["add_circle"](circle))["status"] == "success"
        assert (await tools["exit_sketch"]())["status"] == "success"

    await _circle(0, 30)
    boss = await tools["create_extrusion"]({"depth": _THICK})
    assert boss["status"] == "success", boss
    await _circle(_HOLE_AT, _HOLE_R)
    cut = await tools["create_cut_extrude"](
        {"end_condition": "ThroughAll", "depth": 10}
    )
    assert cut["status"] == "success", cut
    return str(cut["cut_extrude"]["name"])


async def _rim_centres(tools: dict[str, Any], feature: str) -> list[list[float]]:
    rims = await tools["select_edges"]({"feature": feature, "edge_type": "circular"})
    assert rims["status"] == "success", rims
    return [e["center_mm"] for e in rims["data"]["edges"]]


async def _pattern_angles(
    adapter: Any, tools: dict[str, Any], reverse: bool
) -> list[int]:
    """Pattern the hole 3 times, 60 degrees apart; the new holes' sketch angles."""
    assert (await adapter.create_part()).is_success
    hole = await _disc_with_hole(tools)
    axis = await tools["create_axis"]({"reference": "y"})
    assert axis["status"] == "success", axis
    before = await _volume(adapter)

    pattern = await tools["pattern_circular"](
        {
            "features": [hole],
            "axis": axis["axis"]["name"],
            "count": 3,
            "step_angle": 60,
            "reverse_direction": reverse,
        }
    )
    assert pattern["status"] == "success", pattern
    after = await _volume(adapter)
    expected = 2 * math.pi * _HOLE_R**2 * _THICK
    assert before - after == pytest.approx(expected, rel=1e-3)
    centres = await _rim_centres(tools, pattern["pattern"]["name"])
    # Top rims only (y = 5); on Top, sketch y is model -Z.
    angles = sorted(
        round(math.degrees(math.atan2(-c[2], c[0]))) for c in centres if c[1] > 1
    )
    evidence(
        f"3 holes, step 60, reverse={reverse} (expect -{expected:.1f} mm³)",
        {"pattern": pattern["pattern"], "change": after - before, "angles": angles},
    )
    return angles


@pytest.mark.asyncio
async def test_step_angle_puts_holes_sixty_degrees_apart(scratch) -> None:
    """Two new holes at 60 and 120 degrees; reversed, at -60 and -120."""
    adapter = scratch.adapter
    tools = await _tools(adapter)

    forward = await _pattern_angles(adapter, tools, reverse=False)
    backward = await _pattern_angles(adapter, tools, reverse=True)

    # Which way is positive about +Y is SolidWorks' choice; reversing must
    # mirror it.
    assert sorted(abs(a) for a in forward) == [60, 120]
    assert sorted(-a for a in backward) == forward


@pytest.mark.asyncio
async def test_planes_and_sketches_hide_and_come_back(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    sketch = await tools["create_sketch"]({"plane": "Front"})
    assert (await tools["add_circle"]({"center_x": 0, "center_y": 0, "radius": 5}))[
        "status"
    ] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"

    hidden = await tools["set_visibility"]({"visible": False, "types": ["planes"]})
    shown = await tools["set_visibility"]({"visible": True, "types": ["planes"]})
    by_name = await tools["set_visibility"](
        {"visible": False, "names": ["Top Plane", sketch["sketch"]["name"]]}
    )

    evidence(
        "hide every plane, show them again, hide one plane and the sketch", by_name
    )
    assert hidden["data"]["types"]["planes"]["after"] is False
    assert shown["data"]["types"]["planes"]["after"] is True
    assert by_name["status"] == "success", by_name
    assert [f["type"] for f in by_name["data"]["features"]] == [
        "RefPlane",
        "ProfileFeature",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_absorbed", [False, True])
async def test_deleting_a_cut_and_its_sketch(scratch, delete_absorbed) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    hole = await _disc_with_hole(tools)

    result = await tools["delete_feature"](
        {"name": hole, "delete_absorbed": delete_absorbed}
    )
    tree = await tools["list_features"]({})
    names = [f["name"] for f in tree["features"]]

    evidence(f"delete {hole}, delete_absorbed={delete_absorbed}", result)
    assert result["status"] == "success", result
    absorbed = result["data"]["absorbed_sketches"]
    assert len(absorbed) == 1
    if delete_absorbed:
        assert result["data"]["absorbed_sketches_left"] == []
        assert absorbed[0] not in names
    else:
        assert result["data"]["absorbed_sketches_left"] == absorbed
        assert absorbed[0] in names
