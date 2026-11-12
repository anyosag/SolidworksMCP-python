"""The mock's rule-based edge selection on its canned 10 mm block."""

from __future__ import annotations

from typing import Any

import pytest

from solidworks_mcp.adapters.base import ExtrusionParameters
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


@pytest.fixture
async def part() -> MockSolidWorksAdapter:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_part()
    return mock


async def test_every_edge_along_z(part: MockSolidWorksAdapter) -> None:
    result = await part.select_edges({"parallel_to": "z"})

    assert result.is_success, result.error
    data = result.data or {}
    assert data["selected_edges"] == 4
    assert data["matched"] == {"candidates": 12, "parallel_to": 4}
    assert data["source"] == "the part"
    assert data["selection_count"] == 4


async def test_a_face_keeps_its_own_edges(part: MockSolidWorksAdapter) -> None:
    top = await part.select_edges({"side": "top"})
    front = await part.select_edges({"plane": "Front Plane"}, append=True)
    at_point = await part.select_edges({"face_point": [10, 5, 5]})

    assert (top.data or {})["selected_edges"] == 4
    assert (front.data or {})["selection_count"] == 8
    assert all(e["start_mm"][0] == 10.0 for e in (at_point.data or {})["edges"])


async def test_a_hole_rim_appears_once_a_circle_is_sketched(
    part: MockSolidWorksAdapter,
) -> None:
    await part.create_sketch("Front")
    await part.add_circle(5, 5, 2)

    result = await part.select_edges({"side": "+z", "edge_type": "circular"})

    assert (result.data or {})["edges"][0]["center_mm"] == [5.0, 5.0, 10.0]


async def test_a_known_feature_gives_the_block(part: MockSolidWorksAdapter) -> None:
    await part.create_sketch("Top")
    await part.add_rectangle(0, 0, 10, 10)
    await part.exit_sketch()
    boss = await part.create_extrusion(ExtrusionParameters(depth=10))

    result = await part.select_edges(
        {"feature": boss.data.name, "inside_box": [[0, 0, 0], [10, 10, 0]]}
    )

    assert (result.data or {})["selected_edges"] == 4


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (
            {"feature": "Nope"},
            "Feature 'Nope' not found; list_features names the features.",
        ),
        ({"face_point": [50, 50, 50]}, "No face found at point [50, 50, 50] mm."),
        ({"plane": "Top Plane"}, "No body face lies on 'Top Plane'."),
        ({"side": "up"}, "Unknown side"),
        (
            {"min_length": 11},
            "No matching edges found: the part has 12 edge(s); 0 pass length.",
        ),
    ],
)
async def test_refusals_match_the_live_wording(
    part: MockSolidWorksAdapter, query: dict[str, Any], message: str
) -> None:
    result = await part.select_edges(query)

    assert message in (result.error or "")


async def test_a_part_is_needed() -> None:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    assert (await mock.select_edges({})).error == "No active model"
    await mock.create_assembly()
    assert (await mock.select_edges({})).error == (
        "select_edges requires an active part document."
    )


async def test_any_of_unites_the_rules(part: MockSolidWorksAdapter) -> None:
    result = await part.select_edges(
        {
            "any_of": [
                {"side": "top"},
                {"side": "bottom"},
                {"parallel_to": "z"},  # already in the two faces: counted once
                {"parallel_to": "y"},  # the uprights
            ]
        }
    )

    assert result.is_success, result.error
    data = result.data or {}
    assert data["selected_edges"] == 12  # 4 top, 4 bottom, 4 upright
    assert data["source"] == "the top face and the bottom face and the part"
    assert [counts["candidates"] for counts in data["matched"]["rules"]] == [
        4,
        4,
        12,
        12,
    ]


async def test_any_of_with_a_missing_feature_is_an_error(
    part: MockSolidWorksAdapter,
) -> None:
    result = await part.select_edges({"any_of": [{"side": "top"}, {"feature": "Nope"}]})

    assert result.error == "Feature 'Nope' not found; list_features names the features."
