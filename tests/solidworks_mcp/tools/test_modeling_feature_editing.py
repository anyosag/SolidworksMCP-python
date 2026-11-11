"""``edit_feature`` and ``set_rollback`` on the mock, and their input rules."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import ExtrusionParameters, RevolveParameters
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.modeling import register_modeling_tools


@pytest.fixture
async def part(mock_config: Any) -> tuple[MockSolidWorksAdapter, dict[str, Any]]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    await adapter.create_sketch("Top")
    await adapter.add_rectangle(0, 0, 10, 10)
    await adapter.exit_sketch()
    await adapter.create_extrusion(ExtrusionParameters(depth=5))
    mcp = FastMCP("feature-editing")
    await register_modeling_tools(mcp, adapter, mock_config)
    return adapter, {tool.name: tool.fn for tool in await mcp.list_tools()}


async def _boss_name(adapter: MockSolidWorksAdapter) -> str:
    return next(f.name for f in adapter._features.values() if f.type == "Extrusion")


async def test_a_boss_gets_deeper_in_place(part: Any) -> None:
    adapter, tools = part
    boss = await _boss_name(adapter)

    result = await tools["edit_feature"](
        {"name": boss, "depth": 8, "end_condition": "mid plane"}
    )

    assert result["status"] == "success", result
    assert result["data"]["before"] == {"depth": 5, "end_condition": "Blind"}
    assert result["data"]["after"] == {"depth": 8, "end_condition": "MidPlane"}
    assert result["message"] == f"Changed {boss}: depth 8, end_condition MidPlane"


async def test_a_revolve_angle_and_a_fillet_radius(part: Any) -> None:
    adapter, tools = part
    await adapter.create_sketch("Front")
    await adapter.add_rectangle(5, 0, 8, 4)
    await adapter.add_centerline(0, 0, 0, 10)
    await adapter.exit_sketch()
    revolve = await adapter.create_revolve(RevolveParameters(angle=180))
    fillet = await adapter.add_fillet(1.0, ["Edge1"])

    turned = await tools["edit_feature"]({"name": revolve.data.name, "angle": 90})
    rounded = await tools["edit_feature"]({"name": fillet.data.name, "radius": 2})

    assert turned["data"]["type"] == "Revolution"
    assert turned["data"]["after"] == {"angle": 90}
    assert rounded["data"]["before"] == {"radius": 1.0}


@pytest.mark.parametrize(
    ("arguments", "error_type", "fragment"),
    [
        ({"name": "Boss-Extrude1"}, "invalid_input", "give at least one change"),
        ({"name": " ", "depth": 3}, "invalid_input", "name is required"),
        ({"name": "Nope", "depth": 3}, "not_found", "'Nope' not found"),
        ({"name": "Boss-Extrude1", "radius": 2}, "operation_failed", "not radius"),
        ({"name": "Boss-Extrude1", "depth": -1}, "invalid_input", "greater than 0"),
    ],
)
async def test_edit_refusals(
    part: Any, arguments: dict[str, Any], error_type: str, fragment: str
) -> None:
    _adapter, tools = part

    result = await tools["edit_feature"](arguments)

    assert result["status"] == "error"
    assert fragment in result["message"]
    if error_type != "operation_failed":
        assert result["error_type"] == error_type


async def test_the_rollback_bar_moves_and_comes_back(part: Any) -> None:
    adapter, tools = part
    boss = await _boss_name(adapter)
    await adapter.add_fillet(1.0, ["Edge1"])

    up = await tools["set_rollback"]({"after": boss})
    down = await tools["set_rollback"]()

    assert up["data"]["position"] == f"after {boss}"
    assert up["data"]["rolled_back"] == ["Fillet1"]
    assert up["message"].endswith("; 1 feature(s) below it")
    assert down["message"] == "Rollback bar at the end"


async def test_rollback_refusals(part: Any) -> None:
    adapter, tools = part
    boss = await _boss_name(adapter)

    both = await tools["set_rollback"]({"before": boss, "after": boss})
    missing = await tools["set_rollback"]({"before": "Nope"})
    before = await tools["set_rollback"]({"before": boss})

    assert both["error_type"] == "invalid_input"
    assert missing["error_type"] == "not_found"
    assert before["data"]["rolled_back"][0] == boss


async def test_without_a_document() -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()

    assert (
        await adapter.edit_feature("Boss1", {"depth": 2})
    ).error == "No active model"
    assert (await adapter.set_rollback()).error == "No active model"
    assert (await adapter.edit_sketch("Sketch1")).error == "No active model"
