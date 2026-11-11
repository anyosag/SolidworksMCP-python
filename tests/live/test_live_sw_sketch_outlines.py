"""Sketch outlines, arc direction, sketch axes and planes on real SolidWorks.

From the Cellvis dish-rack session's suggestions: a honeycomb deck took about
150 ``add_line``/``add_arc`` calls, ``add_arc`` could only go
counter-clockwise, and the agent had to work out that a Top-plane sketch's
y runs along model -Z. Each test calls the MCP tools as an agent would, with
plain dicts, and checks the result against a hand calculation:

- the axes ``create_sketch`` reports on the three default planes and an
  offset plane, and XY naming the Front Plane;
- a plane that isn't in the part is ``not_found``, not a sketch on Top;
- a 3 x 3 honeycomb drawn by one ``add_outlines`` call and cut through a
  plate removes 9 hexagons' area x thickness;
- a slot of lines and arcs extrudes to (20 x 10 + pi 5^2) x 5;
- a clockwise arc closes a three-quarter disc, through ``add_arc`` and
  through ``add_outlines``;
- a construction line across a rectangle doesn't split its profile.

Run one with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_sketch_outlines.py::test_a_honeycomb_is_one_outline_call

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.live.evidence import evidence

#: The plate the honeycomb is cut through: 100 x 80 mm, 5 mm thick.
_PLATE_X, _PLATE_Y, _THICK = 100.0, 80.0, 5.0
#: Hexagon circumradius and pitch (5 mm walls between neighbours).
_HEX_R, _PITCH_X, _PITCH_Y = 8.0, 24.0, 20.0


async def _tools(adapter: Any) -> dict[str, Any]:
    """The sketching, modelling and analysis tools against ``adapter``."""
    from fastmcp import FastMCP

    from solidworks_mcp.tools.analysis import register_analysis_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("sketch-outlines-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_analysis_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _volume(adapter: Any) -> float:
    result = await adapter.get_model_geometry_summary()
    assert result.is_success, result.error
    return float(result.data["volume_mm3"])


def _hexagon(cx: float, cy: float) -> list[list[float]]:
    return [
        [
            cx + _HEX_R * math.cos(math.radians(60 * k)),
            cy + _HEX_R * math.sin(math.radians(60 * k)),
        ]
        for k in range(6)
    ]


async def _sketch(tools: dict[str, Any], plane: str) -> dict[str, Any]:
    result = await tools["create_sketch"]({"plane": plane})
    assert result["status"] == "success", result
    return result["sketch"]


async def _closed_and_extruded(tools: dict[str, Any], depth: float) -> dict[str, Any]:
    closed = await tools["exit_sketch"]()
    assert closed["status"] == "success", closed
    return await tools["create_extrusion"]({"depth": depth})


@pytest.mark.asyncio
async def test_create_sketch_reports_each_planes_axes(scratch) -> None:
    """Front: y up; Top: y = -Z; Right: x = -Z; 10 mm above Top: origin y 10."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success

    seen = {}
    for plane in ("XY", "Top", "Right"):
        sketch = await _sketch(tools, plane)
        seen[plane] = sketch
        assert (await tools["exit_sketch"]())["status"] == "success"
    plane = await tools["create_reference_plane"](
        {"reference": "Top Plane", "offset": 10.0}
    )
    assert plane["status"] == "success", plane
    raised = await _sketch(tools, plane["plane"]["name"])
    assert (await tools["exit_sketch"]())["status"] == "success"

    evidence(
        "sketch axes on Front (as XY), Top, Right and a plane 10 mm above Top",
        {name: s.get("axes", {}).get("summary") for name, s in seen.items()}
        | {"offset": raised.get("axes")},
    )
    assert seen["XY"]["plane"] == "Front Plane"
    assert seen["XY"]["axes"]["y"] == [0.0, 1.0, 0.0]
    assert seen["Top"]["axes"]["y"] == [0.0, 0.0, -1.0]
    assert seen["Top"]["axes"]["normal"] == [0.0, 1.0, 0.0]
    assert seen["Right"]["axes"]["x"] == [0.0, 0.0, -1.0]
    assert raised["axes"]["summary"] == seen["Top"]["axes"]["summary"]
    assert raised["axes"]["origin_mm"][1] == pytest.approx(10.0, abs=1e-6)


@pytest.mark.asyncio
async def test_a_missing_plane_is_not_found(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success

    result = await tools["create_sketch"]({"plane": "Plane99"})

    evidence("create_sketch on a plane the part doesn't have", result)
    assert result["status"] == "error"
    assert result["error_type"] == "not_found"


@pytest.mark.asyncio
async def test_a_honeycomb_is_one_outline_call(scratch) -> None:
    """9 hexagons through a 5 mm plate: the volume drops by 9 x (3 sqrt3 / 2) r^2 x 5."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _sketch(tools, "Top")
    plate = await tools["add_rectangle"](
        {
            "x1": -_PLATE_X / 2,
            "y1": -_PLATE_Y / 2,
            "x2": _PLATE_X / 2,
            "y2": _PLATE_Y / 2,
        }
    )
    assert plate["status"] == "success", plate
    boss = await _closed_and_extruded(tools, _THICK)
    assert boss["status"] == "success", boss
    before = await _volume(adapter)

    await _sketch(tools, "Top")
    outlines = [
        {"points": _hexagon(_PITCH_X * i, _PITCH_Y * j)}
        for i in (-1, 0, 1)
        for j in (-1, 0, 1)
    ]
    drawn = await tools["add_outlines"]({"outlines": outlines})
    assert (await tools["exit_sketch"]())["status"] == "success"
    cut = await tools["create_cut_extrude"](
        {"end_condition": "ThroughAll", "depth": 10}
    )
    after = await _volume(adapter)

    hexagon_area = 3 * math.sqrt(3) / 2 * _HEX_R**2
    expected = 9 * hexagon_area * _THICK
    evidence(
        f"one add_outlines call: 9 hexagons, 54 lines (expect -{expected:.1f} mm³)",
        {
            "segments": drawn.get("segment_count"),
            "seconds": drawn.get("execution_time"),
            "cut": cut.get("status"),
            "volume_change_mm3": round(after - before, 1),
        },
    )
    assert drawn["status"] == "success", drawn
    assert drawn["segment_count"] == 54
    assert cut["status"] == "success", cut
    assert before - after == pytest.approx(expected, rel=1e-3)


@pytest.mark.asyncio
async def test_a_slot_of_lines_and_arcs_extrudes(scratch) -> None:
    """A 20 mm slot, 10 mm wide: (20 x 10 + pi 5^2) x 5 mm."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _sketch(tools, "Front")

    slot = {
        "start": [0, -5],
        "segments": [
            {"to": [20, -5]},
            {"type": "arc", "center": [20, 0], "to": [20, 5]},
            {"to": [0, 5]},
            {"type": "arc", "center": [0, 0], "to": [0, -5]},
        ],
    }
    drawn = await tools["add_outlines"]({"outlines": [slot]})
    boss = await _closed_and_extruded(tools, 5.0)
    volume = await _volume(adapter)

    expected = (20 * 10 + math.pi * 25) * 5
    evidence(f"a slot from add_outlines (expect {expected:.1f} mm³)", volume)
    assert drawn["status"] == "success", drawn
    assert (drawn["line_count"], drawn["arc_count"]) == (2, 2)
    assert boss["status"] == "success", boss
    assert volume == pytest.approx(expected, rel=1e-3)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["add_arc", "add_outlines"])
async def test_a_clockwise_arc_closes_three_quarters_of_a_disc(scratch, route) -> None:
    """From (10, 0) clockwise to (0, 10) about the origin is 270 degrees.

    Closed by the two radii, it extrudes to 0.75 x pi 10^2 x 5 = 1178.1 mm³;
    a counter-clockwise arc would give a quarter disc, 392.7 mm³.
    """
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _sketch(tools, "Front")

    if route == "add_arc":
        assert (await tools["add_line"]({"x1": 0, "y1": 0, "x2": 10, "y2": 0}))[
            "status"
        ] == "success"
        arc = await tools["add_arc"](
            {
                "center_x": 0,
                "center_y": 0,
                "start_x": 10,
                "start_y": 0,
                "end_x": 0,
                "end_y": 10,
                "direction": "cw",
            }
        )
        assert arc["status"] == "success", arc
        assert arc["arc"]["sweep_deg"] == pytest.approx(270.0)
        assert (await tools["add_line"]({"x1": 0, "y1": 10, "x2": 0, "y2": 0}))[
            "status"
        ] == "success"
    else:
        drawn = await tools["add_outlines"](
            {
                "outlines": [
                    {
                        "start": [0, 0],
                        "segments": [
                            {"to": [10, 0]},
                            {
                                "type": "arc",
                                "center": [0, 0],
                                "to": [0, 10],
                                "direction": "cw",
                            },
                        ],
                    }
                ]
            }
        )
        assert drawn["status"] == "success", drawn
    boss = await _closed_and_extruded(tools, 5.0)
    volume = await _volume(adapter)

    expected = 0.75 * math.pi * 100 * 5
    evidence(f"clockwise arc via {route} (expect {expected:.1f} mm³)", volume)
    assert boss["status"] == "success", boss
    assert volume == pytest.approx(expected, rel=1e-3)


@pytest.mark.asyncio
async def test_a_construction_line_does_not_split_a_profile(scratch) -> None:
    """A diagonal construction line across a 40 x 20 rectangle: 40 x 20 x 5."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _sketch(tools, "Front")
    assert (await tools["add_rectangle"]({"x1": 0, "y1": 0, "x2": 40, "y2": 20}))[
        "status"
    ] == "success"
    line = await tools["add_line"](
        {"x1": 0, "y1": 0, "x2": 40, "y2": 20, "construction": True}
    )
    boss = await _closed_and_extruded(tools, 5.0)
    volume = await _volume(adapter)

    evidence("a construction diagonal, then extrude (expect 4000 mm³)", volume)
    assert line["status"] == "success", line
    assert boss["status"] == "success", boss
    assert volume == pytest.approx(4000.0, rel=1e-3)
