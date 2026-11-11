"""``select_edges`` on real SolidWorks: a feature's edges, filtered by rule.

From the Cellvis dish-rack session: filleting the edges a latch window cut
made meant picking them one coordinate at a time. Here a 30 x 10 mm window
is cut through a 5 mm plate, then:

- ``feature: "Cut-Extrude1"`` finds the window's 12 edges (4 top, 4 bottom,
  4 vertical), each once although two faces share each;
- ``parallel_to: "y"`` keeps the 4 vertical ones, and a 1 mm fillet on them
  adds 4 x (1 - pi/4) x 1^2 x 5 = 4.29 mm³ (the corners are concave);
- ``inside_box`` around the top face keeps the 4 top rim edges;
- a rule nothing passes is ``not_found`` and names the rule.

Run one with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_select_edges.py::test_a_cuts_vertical_edges_take_a_fillet

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.live.evidence import evidence

_THICK = 5.0


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("select-edges-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _volume(adapter: Any) -> float:
    result = await adapter.get_model_geometry_summary()
    assert result.is_success, result.error
    return float(result.data["volume_mm3"])


async def _plate_with_window(adapter: Any, tools: dict[str, Any]) -> str:
    """A 60 x 40 x 5 plate on Top (y 0..5) with a 30 x 10 window through it."""
    assert (await adapter.create_part()).is_success

    async def _rectangle(x1: float, y1: float, x2: float, y2: float) -> None:
        assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
        drawn = await tools["add_rectangle"]({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        assert drawn["status"] == "success", drawn
        assert (await tools["exit_sketch"]())["status"] == "success"

    await _rectangle(-30, -20, 30, 20)
    boss = await tools["create_extrusion"]({"depth": _THICK})
    assert boss["status"] == "success", boss
    await _rectangle(-15, -5, 15, 5)
    cut = await tools["create_cut_extrude"](
        {"end_condition": "ThroughAll", "depth": 10}
    )
    assert cut["status"] == "success", cut
    return str(cut["cut_extrude"]["name"])


@pytest.mark.asyncio
async def test_a_cuts_edges_are_found_once_each(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    cut = await _plate_with_window(adapter, tools)

    result = await tools["select_edges"]({"feature": cut})

    evidence(f"select_edges feature={cut!r} (expect 12 edges)", result.get("data"))
    assert result["status"] == "success", result
    assert result["data"]["selected_edges"] == 12
    assert result["data"]["selection_count"] == 12


@pytest.mark.asyncio
async def test_a_cuts_vertical_edges_take_a_fillet(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    cut = await _plate_with_window(adapter, tools)
    before = await _volume(adapter)

    picked = await tools["select_edges"]({"feature": cut, "parallel_to": "y"})
    fillet = await tools["add_fillet"]({"radius": 1.0, "edge_names": []})
    after = await _volume(adapter)

    expected = 4 * (1 - math.pi / 4) * 1.0**2 * _THICK
    evidence(
        f"vertical edges of the window, then a 1 mm fillet (expect +{expected:.2f} mm³)",
        {"picked": picked.get("data", {}).get("matched"), "change": after - before},
    )
    assert picked["status"] == "success", picked
    assert picked["data"]["selected_edges"] == 4
    assert fillet["status"] == "success", fillet
    assert after - before == pytest.approx(expected, rel=0.02)


@pytest.mark.asyncio
async def test_a_box_keeps_the_top_rim(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    cut = await _plate_with_window(adapter, tools)

    result = await tools["select_edges"](
        {"feature": cut, "inside_box": [[-20, 4.9, -10], [20, 5.1, 10]]}
    )

    evidence(
        "the window's edges inside a thin box at y = 5 (expect 4)", result.get("data")
    )
    assert result["status"] == "success", result
    assert result["data"]["selected_edges"] == 4
    assert all(e["curve"] == "linear" for e in result["data"]["edges"])


@pytest.mark.asyncio
async def test_a_rule_nothing_passes_is_not_found(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    cut = await _plate_with_window(adapter, tools)

    result = await tools["select_edges"]({"feature": cut, "edge_type": "circular"})

    evidence("the window's circular edges (it has none)", result)
    assert result["status"] == "error"
    assert result["error_type"] == "not_found"
    assert "0 pass edge_type" in result["message"]
