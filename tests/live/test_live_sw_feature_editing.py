"""Editing an existing model in place, on real SolidWorks.

From the Cellvis dish-rack session: deleting a feature to rebuild it took
two fillets with it. Each test changes a feature where it stands and checks
the volume against a hand calculation, with the feature count unchanged:

- ``edit_feature``: a 40 x 30 boss from 10 to 20 mm deep doubles its volume;
  a 1 mm fillet made 2 mm removes more; a blind hole made ``ThroughAll``
  goes through;
- ``set_rollback``: a hole added with the bar after the boss lands before
  the fillet in the tree, and the bar goes back to the end;
- ``edit_sketch``: the hole's circle is replaced by a bigger one and the cut
  follows, without deleting the cut.

Run one with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_feature_editing.py::test_a_boss_gets_deeper_in_place

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.file_management import register_file_management_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("feature-editing-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_file_management_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _volume(adapter: Any) -> float:
    result = await adapter.get_model_geometry_summary()
    assert result.is_success, result.error
    return float(result.data["volume_mm3"])


async def _names(tools: dict[str, Any]) -> list[str]:
    return [f["name"] for f in (await tools["list_features"]({}))["features"]]


async def _block(adapter: Any, tools: dict[str, Any]) -> str:
    """A 40 x 30 x 10 mm block on Top; returns the boss's name."""
    assert (await adapter.create_part()).is_success
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    drawn = await tools["add_rectangle"]({"x1": -20, "y1": -15, "x2": 20, "y2": 15})
    assert drawn["status"] == "success", drawn
    assert (await tools["exit_sketch"]())["status"] == "success"
    boss = await tools["create_extrusion"]({"depth": 10.0})
    assert boss["status"] == "success", boss
    return str(boss["extrusion"]["name"])


async def _hole(tools: dict[str, Any], radius: float, through: bool) -> tuple[str, str]:
    """A hole at the origin from the Top Plane; returns (cut, sketch) names."""
    sketch = await tools["create_sketch"]({"plane": "Top"})
    assert (
        await tools["add_circle"]({"center_x": 0, "center_y": 0, "radius": radius})
    )["status"] == "success"
    closed = await tools["exit_sketch"]()
    assert closed["status"] == "success", closed
    call = (
        {"depth": 4.0} if not through else {"end_condition": "ThroughAll", "depth": 10}
    )
    cut = await tools["create_cut_extrude"](call)
    assert cut["status"] == "success", cut
    return str(cut["cut_extrude"]["name"]), str(
        (closed.get("sketch") or sketch["sketch"])["name"]
    )


@pytest.mark.asyncio
async def test_a_boss_gets_deeper_in_place(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    boss = await _block(adapter, tools)
    before = await _volume(adapter)
    names = await _names(tools)

    result = await tools["edit_feature"]({"name": boss, "depth": 20})
    after = await _volume(adapter)

    evidence(f"{boss} from 10 to 20 mm deep (expect 24000 mm³)", result.get("data"))
    assert result["status"] == "success", result
    assert result["data"]["before"]["depth"] == pytest.approx(10.0)
    assert result["data"]["after"]["depth"] == pytest.approx(20.0)
    assert (before, after) == (
        pytest.approx(12000, rel=1e-4),
        pytest.approx(24000, rel=1e-4),
    )
    assert await _names(tools) == names


@pytest.mark.asyncio
async def test_a_fillet_radius_and_a_through_hole(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _block(adapter, tools)
    cut, _sketch = await _hole(tools, radius=3.0, through=False)
    picked = await tools["select_face_edges"]({"side": "top", "edge_type": "linear"})
    assert picked["status"] == "success", picked
    fillet = await tools["add_fillet"]({"radius": 1.0, "edge_names": []})
    assert fillet["status"] == "success", fillet
    fillet_name = fillet["fillet"]["name"]
    at_1mm = await _volume(adapter)

    radius = await tools["edit_feature"]({"name": fillet_name, "radius": 2})
    at_2mm = await _volume(adapter)
    through = await tools["edit_feature"]({"name": cut, "end_condition": "ThroughAll"})
    holed = await _volume(adapter)

    # A convex fillet removes (1 - pi/4) r^2 per mm of edge; the top rim is
    # 140 mm. At each of the 4 corners two of those cuts overlap, by
    # (2 - pi/2 - 1/3) r^3 (measured 87.43 mm³ against 87.45 from this).
    corner = 2 - math.pi / 2 - 1 / 3
    extra = (1 - math.pi / 4) * (2**2 - 1**2) * 140 - 4 * corner * (2**3 - 1**3)
    deeper = math.pi * 3**2 * 6  # the hole goes from 4 to 10 mm deep
    evidence(
        "fillet 1 -> 2 mm, then the hole through",
        {"fillet": radius.get("data"), "cut": through.get("data")},
    )
    assert radius["status"] == "success", radius
    assert at_1mm - at_2mm == pytest.approx(extra, rel=0.02)
    assert through["status"] == "success", through
    assert through["data"]["after"]["end_condition"] == "ThroughAll"
    assert at_2mm - holed == pytest.approx(deeper, rel=0.02)


@pytest.mark.asyncio
async def test_a_feature_goes_in_at_the_rollback_bar(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    boss = await _block(adapter, tools)
    assert (await tools["select_face_edges"]({"side": "top", "edge_type": "linear"}))[
        "status"
    ] == "success"
    fillet = await tools["add_fillet"]({"radius": 1.0, "edge_names": []})
    assert fillet["status"] == "success", fillet

    rolled = await tools["set_rollback"]({"after": boss})
    cut, _sketch = await _hole(tools, radius=3.0, through=True)
    forward = await tools["set_rollback"]()
    order = await _names(tools)

    evidence(
        "a hole added with the bar after the boss", {"rolled": rolled, "order": order}
    )
    assert rolled["status"] == "success", rolled
    assert rolled["data"]["rolled_back"]
    assert forward["data"]["rolled_back"] == []
    # list_features lists the newest feature first; put it in tree order.
    tree = order if order.index("Origin") < order.index(boss) else order[::-1]
    assert (
        tree.index(boss)
        < tree.index(cut)
        < tree.index(next(n for n in tree if n.startswith("Fillet")))
    )


@pytest.mark.asyncio
async def test_a_holes_sketch_is_redrawn_bigger(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _block(adapter, tools)
    cut, sketch = await _hole(tools, radius=3.0, through=True)
    before = await _volume(adapter)
    names = await _names(tools)

    opened = await tools["edit_sketch"]({"name": sketch})
    circle = [s["id"] for s in opened["sketch"]["segments"]]
    deleted = await tools["delete_sketch_entities"]({"ids": circle})
    bigger = await tools["add_circle"]({"center_x": 0, "center_y": 0, "radius": 5})
    closed = await tools["exit_sketch"]()
    after = await _volume(adapter)

    evidence(f"{sketch}: r 3 -> 5 mm", {"segments": opened["sketch"]["segments"]})
    assert opened["status"] == "success", opened
    assert len(circle) == 1
    assert deleted["status"] == "success", deleted
    assert bigger["status"] == "success", bigger
    assert closed["status"] == "success", closed
    assert before - after == pytest.approx(math.pi * (5**2 - 3**2) * 10, rel=1e-3)
    assert await _names(tools) == names
