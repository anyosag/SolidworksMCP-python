"""``add_outlines``, arc direction and the sketch axes ``create_sketch`` reports.

The outline geometry (``Outline.resolve``) is pure and tested directly; the
tools run against the mock adapter, which refuses what the live adapter
refuses.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.sketching import (
    Outline,
    arc_sweep_deg,
    register_sketching_tools,
)


@pytest.fixture
async def tools(mock_config: Any) -> dict[str, Any]:
    """The sketching tools on a mock part, by name."""
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    mcp = FastMCP("sketch outlines")
    await register_sketching_tools(mcp, adapter, mock_config)
    found = {tool.name: tool.fn for tool in await mcp.list_tools()}
    found["_adapter"] = adapter
    return found


def _hexagon(cx: float, cy: float, r: float) -> list[list[float]]:
    return [
        [
            cx + r * math.cos(math.radians(60 * k)),
            cy + r * math.sin(math.radians(60 * k)),
        ]
        for k in range(6)
    ]


# --- Outline.resolve ----------------------------------------------------------


def test_points_close_with_a_line_back_to_the_first() -> None:
    segments = Outline(points=[[0, 0], [10, 0], [10, 5]]).resolve()

    assert [(s["start"], s["end"]) for s in segments] == [
        ([0.0, 0.0], [10.0, 0.0]),
        ([10.0, 0.0], [10.0, 5.0]),
        ([10.0, 5.0], [0.0, 0.0]),
    ]
    assert {s["type"] for s in segments} == {"line"}


def test_a_repeated_first_point_is_not_a_zero_length_line() -> None:
    segments = Outline(points=[[0, 0], [10, 0], [10, 5], [0, 0.0000001]]).resolve()

    assert len(segments) == 3
    assert segments[-1]["end"] == [0.0, 0.0]


def test_an_open_chain_is_not_closed() -> None:
    segments = Outline(points=[[0, 0], [10, 0], [10, 5]], closed=False).resolve()

    assert len(segments) == 2


def test_each_segment_starts_exactly_where_the_last_ended() -> None:
    """Shared endpoints are the same numbers, so SolidWorks sees one loop."""
    segments = Outline(
        start=[0, -5],
        segments=[
            {"to": [20, -5]},
            {"type": "arc", "center": [20, 0], "to": [20, 5]},
            {"to": [0, 5]},
            {"type": "arc", "center": [0, 0], "to": [0, -5.0000004]},
        ],
    ).resolve()

    for before, after in zip(segments, segments[1:], strict=False):
        assert before["end"] is after["start"]
    # The last arc ends within 0.001 mm of the start, so it ends on it.
    assert segments[-1]["end"] == [0.0, -5.0]
    assert len(segments) == 4
    assert segments[1]["direction"] == "ccw"


def test_a_closed_chain_that_stops_short_gets_a_closing_line() -> None:
    segments = Outline(
        start=[0, 0], segments=[{"to": [10, 0]}, {"to": [10, 10]}]
    ).resolve()

    assert segments[-1] == {"type": "line", "start": [10.0, 10.0], "end": [0.0, 0.0]}


@pytest.mark.parametrize(
    ("outline", "message"),
    [
        ({"points": [[0, 0], [1, 1]]}, "at least 3 distinct points"),
        ({"points": [[0, 0]], "closed": False}, "at least 2 distinct points"),
        ({"points": [[0, 0], [0, 0], [1, 1]]}, "segment 0 ends where it starts"),
        ({"start": [0, 0], "segments": []}, "'segments' is empty"),
        ({"segments": [{"to": [1, 0]}]}, "'segments' needs 'start'"),
        ({}, "give either 'points' or 'start' with 'segments'"),
        (
            {"points": [[0, 0], [1, 0], [1, 1]], "segments": [{"to": [1, 0]}]},
            "give either 'points'",
        ),
        ({"start": [0, 0], "points": [[0, 0], [1, 0], [1, 1]]}, "'start' goes with"),
        (
            {
                "start": [5, 0],
                "segments": [{"type": "arc", "center": [0, 0], "to": [5, 0]}],
            },
            "draw a full circle with add_circle",
        ),
        (
            {
                "start": [0, 0],
                "segments": [{"type": "arc", "center": [0, 0], "to": [5, 0]}],
            },
            "the arc's centre is its start",
        ),
        (
            {
                "start": [5, 0],
                "segments": [{"type": "arc", "center": [0, 0], "to": [0, 5.1]}],
            },
            "0.1 mm off the circle of radius 5",
        ),
        (
            {"start": [0, 0], "segments": [{"type": "arc", "to": [5, 0]}]},
            "an arc needs",
        ),
        (
            {"start": [0, 0], "segments": [{"center": [1, 1], "to": [5, 0]}]},
            "a line takes no 'center'",
        ),
        (
            {"start": [0, 0], "segments": [{"to": [5, 0], "end": [1, 1]}]},
            "Extra inputs",
        ),
    ],
)
def test_degenerate_outlines_are_refused(outline: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=None) as caught:
        Outline.model_validate(outline)
    assert message in str(caught.value)


@pytest.mark.parametrize(
    ("direction", "end", "sweep"),
    [("ccw", [0, 10], 90.0), ("cw", [0, 10], 270.0), ("cw", [0, -10], 90.0)],
)
def test_arc_sweep_follows_the_direction(
    direction: str, end: list[float], sweep: float
) -> None:
    assert arc_sweep_deg([0, 0], [10, 0], end, direction) == pytest.approx(sweep)


# --- the tools on the mock ------------------------------------------------------


async def test_a_honeycomb_is_one_call(tools: dict[str, Any]) -> None:
    """25 hexagons, 150 lines: the call the dish rack needed ~150 of."""
    await tools["create_sketch"]({"plane": "Top"})
    outlines = [
        {"points": _hexagon(12 * i, 10.4 * j, 5.5)} for i in range(5) for j in range(5)
    ]

    result = await tools["add_outlines"]({"outlines": outlines})

    assert result["status"] == "success", result
    assert result["segment_count"] == 150
    assert (result["line_count"], result["arc_count"]) == (150, 0)
    assert len(result["outlines"]) == 25
    ids = [i for outline in result["outlines"] for i in outline["ids"]]
    assert len(set(ids)) == 150
    assert result["outlines"][0]["closed"] is True
    assert result["message"] == "Drew 25 outline(s): 150 segments (150 lines, 0 arcs)"


async def test_outlines_need_an_open_sketch(tools: dict[str, Any]) -> None:
    result = await tools["add_outlines"]({"outlines": [{"points": _hexagon(0, 0, 5)}]})

    assert result["status"] == "error"
    assert result["error_type"] == "no_active_sketch"


async def test_a_bad_outline_names_itself(tools: dict[str, Any]) -> None:
    await tools["create_sketch"]({"plane": "Top"})

    result = await tools["add_outlines"](
        {"outlines": [{"points": _hexagon(0, 0, 5)}, {"points": [[0, 0], [1, 0]]}]}
    )

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_input"
    assert "outlines.1" in result["message"]


async def test_too_many_segments_are_refused(tools: dict[str, Any]) -> None:
    await tools["create_sketch"]({"plane": "Top"})
    big = [
        [math.cos(k / 500 * math.tau), math.sin(k / 500 * math.tau)] for k in range(500)
    ]

    result = await tools["add_outlines"]({"outlines": [{"points": big}] * 5})

    assert result["status"] == "error"
    assert "2500 segments in one call; the most is 2000" in result["message"]


async def test_create_sketch_reports_the_axes(tools: dict[str, Any]) -> None:
    result = await tools["create_sketch"]({"plane": "XZ"})

    assert result["sketch"]["plane"] == "Top Plane"
    assert result["sketch"]["axes"]["y"] == [0.0, 0.0, -1.0]
    assert "sketch y = model -Z" in result["message"]


async def test_create_sketch_on_a_missing_plane_is_not_found(
    tools: dict[str, Any],
) -> None:
    result = await tools["create_sketch"]({"plane": "Plane7"})

    assert result["status"] == "error"
    assert result["error_type"] == "not_found"
    assert "Plane 'Plane7' not found" in result["message"]


async def test_create_sketch_on_a_reference_plane_has_no_mock_axes(
    tools: dict[str, Any],
) -> None:
    adapter: MockSolidWorksAdapter = tools["_adapter"]
    plane = await adapter.create_reference_plane(reference="Top Plane", offset=10.0)
    name = plane.data["name"]

    result = await tools["create_sketch"]({"plane": name})

    assert result["status"] == "success", result
    assert result["sketch"]["plane"] == name
    assert "axes" not in result["sketch"]


async def test_add_arc_reports_direction_radius_and_sweep(
    tools: dict[str, Any],
) -> None:
    await tools["create_sketch"]({"plane": "Front"})

    result = await tools["add_arc"](
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

    assert result["status"] == "success", result
    assert result["arc"]["direction"] == "cw"
    assert result["arc"]["radius"] == 10.0
    assert result["arc"]["sweep_deg"] == 270.0
    assert result["message"].startswith("Added cw arc")


async def test_a_construction_rectangle_is_construction(tools: dict[str, Any]) -> None:
    await tools["create_sketch"]({"plane": "Front"})

    result = await tools["add_rectangle"](
        {"x1": 0, "y1": 0, "x2": 10, "y2": 5, "construction": True}
    )

    assert result["status"] == "success", result
    assert result["rectangle"]["construction"] is True
