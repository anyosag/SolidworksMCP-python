"""``list_features``' filters: standard items, types and the newest N."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.file_management import (
    filter_features,
    register_file_management_tools,
)


def _row(name: str, kind: str, position: int, component: str | None = None) -> dict:
    return {
        "name": name,
        "type": kind,
        "suppressed": False,
        "position": position,
        "component": component,
        "component_path": None,
        "component_parent": None,
    }


#: A part's tree as SolidWorks 2026 lists it, folders and all.
_PART_TREE = [
    _row(name, kind, position)
    for position, (name, kind) in enumerate(
        [
            ("Favorites", "FavoriteFolder"),
            ("Selection Sets", "SelectionSetFolder"),
            ("Sensors", "SensorFolder"),
            ("Design Binder", "DocsFolder"),
            ("Annotations", "DetailCabinet"),
            ("Surface Bodies", "SurfaceBodyFolder"),
            ("Solid Bodies", "SolidBodyFolder"),
            ("Equations", "EqnFolder"),
            ("Material <not specified>", "MaterialFolder"),
            ("Lights, Cameras and Scene", "EnvFolder"),
            ("Markups", "InkMarkupFolder"),
            ("Front Plane", "RefPlane"),
            ("Top Plane", "RefPlane"),
            ("Right Plane", "RefPlane"),
            ("Origin", "OriginProfileFeature"),
            ("Sketch1", "ProfileFeature"),
            ("Boss-Extrude1", "Extrusion"),
            ("Sketch2", "ProfileFeature"),
            ("Cut-Extrude1", "ICE"),
            ("Plane1", "RefPlane"),
            ("Ribs", "FtrFolder"),
            ("Fillet1", "Fillet"),
        ]
    )
]


@pytest.fixture
async def list_features(mock_config: Any) -> tuple[MockSolidWorksAdapter, Any]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    mcp = FastMCP("list-features")
    await register_file_management_tools(mcp, adapter, mock_config)
    tool = next(t.fn for t in await mcp.list_tools() if t.name == "list_features")
    return adapter, tool


def _serve(adapter: MockSolidWorksAdapter, rows: list[dict]) -> None:
    adapter.list_features = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(status=AdapterResultStatus.SUCCESS, data=rows)
    )


def _names(reply: dict[str, Any]) -> list[str]:
    return [row["name"] for row in reply["features"]]


async def test_a_part_is_listed_once(list_features: Any) -> None:
    adapter, tool = list_features
    _serve(adapter, _PART_TREE)

    reply = await tool({})
    unfiltered = await tool({"types": None, "last": None})

    assert reply["status"] == "success", reply
    assert reply["count"] == reply["total"] == len(_PART_TREE)
    assert "assembly_tree" not in reply
    assert unfiltered["features"] == reply["features"]


async def test_the_standard_items_can_be_left_out(list_features: Any) -> None:
    adapter, tool = list_features
    _serve(adapter, _PART_TREE)

    reply = await tool({"include_standard": False})

    assert _names(reply) == [
        "Sketch1",
        "Boss-Extrude1",
        "Sketch2",
        "Cut-Extrude1",
        "Plane1",
        "Ribs",
        "Fillet1",
    ]
    assert (reply["count"], reply["total"]) == (7, len(_PART_TREE))


async def test_types_match_in_any_case_and_cut_matches_ice(list_features: Any) -> None:
    adapter, tool = list_features
    _serve(adapter, _PART_TREE)

    reply = await tool({"types": ["extrusion", "CUT", "Fillet"]})

    assert _names(reply) == ["Boss-Extrude1", "Cut-Extrude1", "Fillet1"]


async def test_last_applies_after_types(list_features: Any) -> None:
    adapter, tool = list_features
    _serve(adapter, _PART_TREE)

    newest_sketch = await tool({"types": ["ProfileFeature"], "last": 1})
    newest_two = await tool({"last": 2})

    assert _names(newest_sketch) == ["Sketch2"]
    assert _names(newest_two) == ["Ribs", "Fillet1"]


async def test_planes_after_the_three_default_ones_are_kept(
    list_features: Any,
) -> None:
    adapter, tool = list_features
    _serve(adapter, _PART_TREE)

    reply = await tool({"include_standard": False, "types": ["RefPlane"]})

    assert _names(reply) == ["Plane1"]


async def test_an_assembly_keeps_its_tree_and_the_newest_of_each_document(
    list_features: Any,
) -> None:
    adapter, tool = list_features
    await adapter.open_model("C:\\mock\\Assem1.sldasm")

    reply = await tool({"last": 1})

    assert [(row["component"], row["name"]) for row in reply["features"]] == [
        (None, "Sketch1"),
        ("PartA", "Fillet1"),
        ("PartB", "Cut-Extrude1"),
        ("SubAssembly1", "Mate1"),
        ("PartC", "Boss-Extrude1"),
    ]
    assert reply["total"] > reply["count"]
    assert reply["assembly_tree"]["features"] == [reply["features"][0]]
    assert set(reply["assembly_tree"]["components"]) == {
        "PartA",
        "PartB",
        "SubAssembly1",
    }


def test_newest_follows_the_tree_position_not_the_list_order() -> None:
    # The adapter's fallback walk lists the features it found newest first.
    rows = [_row("Boss-Extrude1", "Extrusion", 1), _row("Sketch1", "ProfileFeature", 0)]
    unnumbered = [{"name": "A", "type": "Extrusion"}, {"name": "B", "type": "Cut"}]

    assert filter_features(rows, last=1) == [rows[0]]
    assert filter_features(unnumbered, last=1) == [unnumbered[1]]
    assert filter_features(rows) == rows


@pytest.mark.parametrize(
    "arguments", [{"last": 0}, {"types": []}, {"types": ["Extrusion", "  "]}]
)
async def test_bad_filters_are_refused(list_features: Any, arguments: dict) -> None:
    adapter, tool = list_features
    _serve(adapter, _PART_TREE)

    reply = await tool(arguments)

    assert reply["error_type"] == "invalid_input", reply
    adapter.list_features.assert_not_awaited()
