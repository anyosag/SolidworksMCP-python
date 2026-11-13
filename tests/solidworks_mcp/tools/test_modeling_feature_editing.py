"""``edit_feature`` and ``set_rollback`` on the mock, and their input rules."""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    ExtrusionParameters,
    RevolveParameters,
)
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


async def test_a_fillet_gets_the_selected_edges(part: Any) -> None:
    adapter, tools = part
    fillet = await adapter.add_fillet(1.0, ["Edge1"])
    await tools["select_edges"]({"side": "top"})

    result = await tools["edit_feature"](
        {"name": fillet.data.name, "edges": "selection", "radius": 2}
    )

    assert result["status"] == "success", result
    assert result["message"] == (
        f"Changed {fillet.data.name}: radius 2, edges 4 given, 4 kept (had 1)"
    )
    assert result["data"]["edges_given"] == 4
    assert "SolidWorks kept" not in (result.get("warning") or "")


async def test_a_chamfer_rule_reaches_the_adapter_as_select_edges_takes_it(
    part: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, tools = part
    chamfer = await adapter.add_chamfer(1.0, ["Edge1"])
    seen: list[dict[str, Any]] = []
    edit = adapter.edit_feature

    async def spy(name: str, changes: dict[str, Any]) -> Any:
        seen.append(changes)
        return await edit(name, changes)

    monkeypatch.setattr(adapter, "edit_feature", spy)

    result = await tools["edit_feature"](
        {
            "name": chamfer.data.name,
            "edge_rules": {"side": "top", "edge_type": " Linear "},
        }
    )

    assert result["status"] == "success", result
    assert seen == [{"edge_rules": {"side": "top", "edge_type": "linear"}}]
    assert result["message"].endswith("edges 4 given, 4 kept (had 1)")


@pytest.mark.parametrize(
    ("data", "warning", "shown"),
    [
        (
            {"edges_before": 1, "edges_given": 4, "edges_after": 2},
            "SolidWorks kept 2 of the 4 edges given: it dropped 2. It drops edges "
            "a fillet can't take, such as its own tangent edges.",
            "edges 4 given, 2 kept (had 1)",
        ),
        (
            {"edges_before": None, "edges_given": 3, "edges_after": None},
            None,
            "edges 3 given, ? kept (had ?)",
        ),
    ],
)
async def test_edges_solidworks_dropped_are_a_warning(
    part: Any,
    monkeypatch: pytest.MonkeyPatch,
    data: dict[str, Any],
    warning: str | None,
    shown: str,
) -> None:
    adapter, tools = part

    async def kept(name: str, changes: dict[str, Any]) -> AdapterResult[Any]:
        reply = {"feature": name, "type": "Fillet", "before": {}, "after": {}}
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data=reply | data)

    monkeypatch.setattr(adapter, "edit_feature", kept)

    result = await tools["edit_feature"]({"name": "Fillet1", "edges": "selection"})

    assert result["message"] == f"Changed Fillet1: {shown}"
    if warning is None:
        assert "SolidWorks kept" not in (result.get("warning") or "")
    else:
        assert result["warning"].startswith(warning)


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        (
            {"name": "Fillet1", "edges": "selection", "edge_rules": {"side": "top"}},
            "give edges or edge_rules, not both",
        ),
        ({"name": "Fillet1", "edges": "all"}, "edges: Input should be 'selection'"),
        ({"name": "Fillet1", "edge_rules": {"sides": "top"}}, "unknown key(s) sides"),
        (
            {"name": "Fillet1", "edge_rules": {"edge_type": "round"}},
            "edge_rules: edge_type must be one of",
        ),
    ],
)
async def test_edge_inputs_that_are_refused(
    part: Any, arguments: dict[str, Any], fragment: str
) -> None:
    _adapter, tools = part

    result = await tools["edit_feature"](arguments)

    assert result["error_type"] == "invalid_input"
    assert fragment in result["message"]


async def test_no_selected_edges_are_invalid_input(part: Any) -> None:
    adapter, tools = part
    fillet = await adapter.add_fillet(1.0, ["Edge1"])

    result = await tools["edit_feature"](
        {"name": fillet.data.name, "edges": "selection"}
    )

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_input"
    assert "so it is unchanged: nothing is selected" in result["message"]
    assert "Select its new edges first" in result["hint"]


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
