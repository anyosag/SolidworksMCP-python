"""The mock's ``edit_feature`` replacing a fillet's or chamfer's edges."""

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
    await mock.create_sketch("Top")
    await mock.add_rectangle(0, 0, 10, 10)
    await mock.exit_sketch()
    await mock.create_extrusion(ExtrusionParameters(depth=10))
    return mock


def _parameters(mock: MockSolidWorksAdapter, name: str) -> dict[str, Any]:
    feature = next(f for f in mock._features.values() if f.name == name)
    return feature.parameters or {}


async def test_a_fillet_takes_the_selected_edges(part: MockSolidWorksAdapter) -> None:
    await part.add_fillet(1.0, ["Edge1"])
    await part.select_edges({"side": "top"})

    result = await part.edit_feature("Fillet1", {"edges": "selection", "radius": 2})

    assert result.is_success, result.error
    data = result.data or {}
    assert (data["edges_before"], data["edges_given"], data["edges_after"]) == (
        1,
        4,
        4,
    )
    assert (data["before"], data["after"]) == ({"radius": 1.0}, {"radius": 2})
    assert _parameters(part, "Fillet1")["edges"] == ["Edge0", "Edge1", "Edge2", "Edge3"]


async def test_a_chamfer_moves_to_the_edges_a_rule_matches(
    part: MockSolidWorksAdapter,
) -> None:
    await part.add_chamfer(1.0, ["Edge1"])

    result = await part.edit_feature(
        "Chamfer1", {"edge_rules": {"side": "top", "edge_type": "Linear"}}
    )

    assert result.is_success, result.error
    data = result.data or {}
    assert data["type"] == "Chamfer"
    assert (data["edges_given"], data["edges_after"]) == (4, 4)
    assert (data["before"], data["after"]) == ({}, {})
    assert _parameters(part, "Chamfer1")["size"] == 1.0


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        (
            {"edges": "selection"},
            "No new edges for 'Fillet1', so it is unchanged: nothing is selected.",
        ),
        (
            {"edge_rules": {"edge_type": "circular"}},
            "no matching edges found: the part has 12 edge(s); 0 pass edge_type.",
        ),
        ({"edge_rules": {"feature": "Nope"}}, "Feature 'Nope' not found"),
        ({"edges": "selection", "edge_rules": {}}, "Give edges or edge_rules, not"),
    ],
)
async def test_no_edges_leave_the_fillet_as_it_was(
    part: MockSolidWorksAdapter, changes: dict[str, Any], fragment: str
) -> None:
    await part.add_fillet(1.0, ["Edge1"])

    result = await part.edit_feature("Fillet1", changes)

    assert not result.is_success
    assert fragment in (result.error or "")
    assert _parameters(part, "Fillet1")["edges"] == ["Edge1"]


async def test_a_selected_feature_is_not_an_edge(part: MockSolidWorksAdapter) -> None:
    await part.add_fillet(1.0, ["Edge1"])
    await part.select_feature("Fillet1")

    result = await part.edit_feature("Fillet1", {"edges": "selection"})

    assert "none of the 1 selected entities is an edge" in (result.error or "")


async def test_other_features_refuse_new_edges(part: MockSolidWorksAdapter) -> None:
    boss = next(f.name for f in part._features.values() if f.type == "Extrusion")

    result = await part.edit_feature(boss, {"edges": "selection"})

    assert result.error == (
        f"{boss!r} is a Extrusion; it takes depth, end_condition, "
        "reverse_direction, not edges."
    )
