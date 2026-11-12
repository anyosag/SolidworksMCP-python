"""The ``select_edges`` tool: rules in, a selection ready for a fillet out."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.modeling import SelectEdgesInput, register_modeling_tools


@pytest.fixture
async def tools(mock_config: Any) -> dict[str, Any]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    mcp = FastMCP("select-edges")
    await register_modeling_tools(mcp, adapter, mock_config)
    return {tool.name: tool.fn for tool in await mcp.list_tools()}


async def test_edges_along_an_axis_then_a_fillet(tools: dict[str, Any]) -> None:
    selected = await tools["select_edges"]({"parallel_to": "z", "edge_type": "linear"})
    fillet = await tools["add_fillet"]({"radius": 1.0, "edge_names": []})

    assert selected["status"] == "success", selected
    assert selected["message"] == "Selected 4 edge(s) of the part"
    assert selected["data"]["matched"]["parallel_to"] == 4
    assert fillet["status"] == "success", fillet


async def test_no_match_is_not_found(tools: dict[str, Any]) -> None:
    result = await tools["select_edges"]({"side": "top", "max_length": 1})

    assert result["status"] == "error"
    assert result["error_type"] == "not_found"
    assert "0 pass length" in result["message"]


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"feature": "Cut-Extrude1", "side": "top"}, "at most one of feature"),
        ({"parallel_to": "w"}, "parallel_to must be"),
        ({"parallel_tolerance_deg": 0}, "greater than 0"),
        ({"min_length": -1}, "greater than or equal to 0"),
    ],
)
async def test_bad_rules_are_invalid_input(
    tools: dict[str, Any], arguments: dict[str, Any], fragment: str
) -> None:
    result = await tools["select_edges"](arguments)

    assert result["error_type"] == "invalid_input"
    assert fragment in result["message"]


def test_the_query_leaves_out_what_was_not_given() -> None:
    query = SelectEdgesInput(feature="Cut-Extrude1", edge_type=" Circular ").query()

    assert query == {
        "feature": "Cut-Extrude1",
        "edge_type": "circular",
        "parallel_tolerance_deg": 1.0,
    }


async def test_several_rules_in_one_call(tools: dict[str, Any]) -> None:
    result = await tools["select_edges"](
        {"any_of": [{"side": "top"}, {"side": "bottom", "edge_type": "Linear"}]}
    )

    assert result["status"] == "success", result
    assert result["data"]["selected_edges"] == 8
    assert len(result["data"]["matched"]["rules"]) == 2


async def test_an_unknown_rule_key_is_invalid_input(tools: dict[str, Any]) -> None:
    result = await tools["select_edges"](
        {"any_of": [{"inside": [[0, 0, 0], [1, 1, 1]]}]}
    )

    assert result["error_type"] == "invalid_input"
    assert "any_of[0] has unknown key(s) inside" in result["message"]
