"""``pattern_circular`` angles, ``set_visibility`` and ``delete_feature``'s sketches.

From the Cellvis dish-rack session: 60-degree steps needed ``angle: 300``
with ``equal_spacing: false`` (SolidWorks read the angle as the step), there
was no way to hide planes and sketches, and deleting a cut left its sketch
without saying so.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    ExtrusionParameters,
)
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.modeling import (
    PatternCircularInput,
    register_modeling_tools,
)


@pytest.fixture
async def part(mock_config: Any) -> tuple[MockSolidWorksAdapter, dict[str, Any]]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    mcp = FastMCP("pattern-visibility-delete")
    await register_modeling_tools(mcp, adapter, mock_config)
    return adapter, {tool.name: tool.fn for tool in await mcp.list_tools()}


# --- pattern_circular ---------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "spacing"),
    [
        ({"count": 6}, (360.0, True, 60.0, 360.0)),
        ({"count": 4, "angle": 180}, (180.0, True, 60.0, 180.0)),
        ({"count": 3, "step_angle": 60}, (60.0, False, 60.0, 120.0)),
    ],
)
def test_spacing_says_both_angles(
    fields: dict[str, Any], spacing: tuple[float, bool, float, float]
) -> None:
    got = PatternCircularInput(features=["Cut1"], axis="Axis1", **fields).spacing()

    assert (
        got["angle"],
        got["equal_spacing"],
        got["step_angle"],
        got["total_angle"],
    ) == spacing


async def test_a_step_angle_reaches_solidworks_as_unequal_spacing(part: Any) -> None:
    adapter, tools = part
    await adapter.create_axis("y")
    seen: dict[str, Any] = {}
    original = adapter.pattern_circular

    async def recording(*args: Any) -> Any:
        seen["args"] = args
        return await original(*args)

    adapter.pattern_circular = recording  # type: ignore[method-assign]

    result = await tools["pattern_circular"](
        {
            "features": ["Cut-Extrude1"],
            "axis": "Axis1",
            "count": 3,
            "step_angle": 60,
            "reverse_direction": True,
        }
    )

    assert result["status"] == "success", result
    assert seen["args"][3:] == (60.0, False, True)
    pattern = result["pattern"]
    assert (pattern["step_angle"], pattern["total_angle"]) == (60.0, 120.0)
    assert pattern["reverse_direction"] is True
    assert "angle" not in pattern and "equal_spacing" not in pattern
    assert result["message"].endswith("(3 instances, 60 degrees apart)")


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"angle": 90, "step_angle": 30}, "not both"),
        ({"step_angle": 72, "count": 6}, "a full turn or more"),
        ({"equal_spacing": False}, "`equal_spacing` is no longer an input"),
        ({"angle": 400}, "less than or equal to 360"),
    ],
)
async def test_contradictory_angles_are_refused(
    part: Any, arguments: dict[str, Any], fragment: str
) -> None:
    _adapter, tools = part
    call = {"features": ["Cut1"], "axis": "Axis1", "count": 3, **arguments}

    result = await tools["pattern_circular"](call)

    assert result["error_type"] == "invalid_input"
    assert fragment in result["message"]


# --- set_visibility -----------------------------------------------------------


async def test_types_are_hidden_and_their_old_state_returned(part: Any) -> None:
    _adapter, tools = part

    result = await tools["set_visibility"](
        {"visible": False, "types": ["planes", "sketches"]}
    )

    assert result["status"] == "success", result
    assert result["data"]["types"] == {
        "planes": {"before": True, "after": False},
        "sketches": {"before": True, "after": False},
    }
    assert result["message"] == "Hid all planes, all sketches"


async def test_a_plane_by_name_is_shown(part: Any) -> None:
    _adapter, tools = part

    result = await tools["set_visibility"]({"visible": True, "names": ["Top Plane"]})

    assert result["data"]["features"] == [
        {"name": "Top Plane", "type": "RefPlane", "visible": True}
    ]
    assert result["message"] == "Showed Top Plane"


@pytest.mark.parametrize(
    ("arguments", "error_type", "fragment"),
    [
        ({"visible": False}, "invalid_input", "give names, types or both"),
        ({"visible": False, "types": ["walls"]}, "invalid_input", "types.0"),
        ({"visible": False, "names": ["Plane9"]}, "not_found", "'Plane9' not found"),
    ],
)
async def test_visibility_refusals(
    part: Any, arguments: dict[str, Any], error_type: str, fragment: str
) -> None:
    _adapter, tools = part

    result = await tools["set_visibility"](arguments)

    assert result["error_type"] == error_type
    assert fragment in result["message"]


async def test_a_boss_is_suppressed_not_hidden(part: Any) -> None:
    adapter, tools = part
    await adapter.create_sketch("Top")
    await adapter.add_rectangle(0, 0, 10, 10)
    await adapter.exit_sketch()
    boss = await adapter.create_extrusion(ExtrusionParameters(depth=5))

    result = await tools["set_visibility"](
        {"visible": False, "names": [boss.data.name]}
    )

    assert result["status"] == "error"
    assert "use suppress_feature" in result["message"]


# --- delete_feature -----------------------------------------------------------


async def _boss(adapter: MockSolidWorksAdapter) -> tuple[str, str]:
    sketch = await adapter.create_sketch("Top")
    await adapter.add_rectangle(0, 0, 10, 10)
    await adapter.exit_sketch()
    boss = await adapter.create_extrusion(
        ExtrusionParameters(depth=5, sketch_name=sketch.data["sketch_name"])
    )
    return boss.data.name, sketch.data["sketch_name"]


async def test_deleting_a_feature_names_the_sketch_it_leaves(part: Any) -> None:
    adapter, tools = part
    boss, sketch = await _boss(adapter)

    result = await tools["delete_feature"]({"name": boss})

    assert result["status"] == "success", result
    assert result["data"]["absorbed_sketches_left"] == [sketch]
    assert f"its sketch {sketch} is still in the tree" in result["message"]
    assert "warning" not in result


async def test_delete_absorbed_takes_the_sketch_too(part: Any) -> None:
    adapter, tools = part
    boss, sketch = await _boss(adapter)

    result = await tools["delete_feature"]({"name": boss, "delete_absorbed": True})

    assert result["data"]["absorbed_sketches_left"] == []
    assert sketch in result["data"]["removed_features"]
    assert result["message"] == f"Deleted {boss}; its sketch {sketch} went with it"
    # The sketch went because it was asked for, not as a dependent.
    assert "warning" not in result


async def test_the_flag_reaches_the_adapter(part: Any) -> None:
    adapter, tools = part
    adapter.delete_feature = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    )

    await tools["delete_feature"]({"name": "Cut1", "delete_absorbed": True})

    adapter.delete_feature.assert_awaited_once_with("Cut1", True)
