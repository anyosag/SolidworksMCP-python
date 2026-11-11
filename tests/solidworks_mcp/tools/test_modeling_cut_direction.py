"""create_cut_extrude passes reverse_direction only when given, and says which side it cut."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    SolidWorksFeature,
)
from solidworks_mcp.tools.modeling import _cut_direction_note, register_modeling_tools


def _cut(**parameters: Any) -> AdapterResult[SolidWorksFeature]:
    return AdapterResult(
        status=AdapterResultStatus.SUCCESS,
        data=SolidWorksFeature(
            name="Cut-Extrude1",
            type="Cut-Extrude",
            parameters={"sketch_name": "Sketch3", **parameters},
        ),
    )


async def _tool(mcp_server, adapter):
    await register_modeling_tools(mcp_server, adapter, {})
    tools = {t.name: t.fn for t in await mcp_server.list_tools()}
    return tools["create_cut_extrude"]


@pytest.mark.asyncio
@pytest.mark.parametrize("given", [{}, {"reverse_direction": False}])
async def test_reverse_direction_reaches_the_adapter_only_when_given(
    mcp_server, mock_adapter, given: dict[str, Any]
) -> None:
    mock_adapter.create_cut_extrude = AsyncMock(return_value=_cut())
    tool = await _tool(mcp_server, mock_adapter)

    result = await tool({"sketch_name": "Sketch3", "depth": 2.0, **given})

    assert result["status"] == "success"
    params = mock_adapter.create_cut_extrude.await_args.args[0]
    assert ("reverse_direction" in params.model_fields_set) is bool(given)
    assert params.reverse_direction is False


@pytest.mark.asyncio
async def test_a_true_reverse_direction_is_passed_on(mcp_server, mock_adapter) -> None:
    mock_adapter.create_cut_extrude = AsyncMock(return_value=_cut())
    tool = await _tool(mcp_server, mock_adapter)

    await tool({"depth": 2.0, "reverse_direction": True})

    params = mock_adapter.create_cut_extrude.await_args.args[0]
    assert params.reverse_direction is True


@pytest.mark.asyncio
async def test_the_message_says_the_cut_took_the_side_with_more_material(
    mcp_server, mock_adapter
) -> None:
    mock_adapter.create_cut_extrude = AsyncMock(
        return_value=_cut(
            direction_flipped=True,
            direction_choice="more_material",
            volume_removed_mm3={"along_normal": 1.13, "against_normal": 9.05},
        )
    )
    tool = await _tool(mcp_server, mock_adapter)

    result = await tool({"depth": 2.0})

    assert result["cut_extrude"]["direction_flipped"] is True
    assert result["message"] == (
        "Created cut-extrude: Cut-Extrude1 (it cut against the sketch normal, the "
        "side with more material: 9.05 mm3 against 1.13 mm3 along it)"
    )


_REQUESTED_FLIPPED = (
    " (the requested direction found no material, so it cut the other way)"
)


@pytest.mark.parametrize(
    ("applied", "note"),
    [
        (None, ""),
        ({}, ""),
        ({"direction_flipped": False, "direction_choice": "more_material"}, ""),
        ({"direction_flipped": False, "direction_choice": "requested"}, ""),
        (
            {"direction_flipped": True, "direction_choice": "only_side_with_material"},
            " (the side along the sketch normal had no material, so it cut the "
            "other way)",
        ),
        (
            {"direction_flipped": True, "direction_choice": "flipped"},
            _REQUESTED_FLIPPED,
        ),
        ({"direction_flipped": True}, _REQUESTED_FLIPPED),
        (
            {
                "direction_flipped": False,
                "direction_choice": "not_compared",
                "direction_note": "the part's volume could not be read",
            },
            " (the two sides were not compared: the part's volume could not be read)",
        ),
        ({"direction_choice": "not_compared"}, ""),
    ],
)
def test_cut_direction_note(applied: Any, note: str) -> None:
    assert _cut_direction_note(applied) == note
