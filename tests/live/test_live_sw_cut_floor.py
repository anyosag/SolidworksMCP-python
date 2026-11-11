"""A blind cut's floor area, and the warning for a cut mostly outside the part.

From the Cellvis dish rack: a cut sketched on an offset plane removed a
1.13 mm³ sliver where 9.05 mm³ was meant, and reported success. Here a 10 mm
square cut 3 mm deep from the top of a 5 mm plate gets a 100 mm² floor and
no warning; the same cut sketched on a plane 2.5 mm above the plate, 3 mm
deep, removes only 0.5 mm of depth, and is warned about.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_cut_floor.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("cut-floor-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _square_cut(tools: dict[str, Any], plane: str) -> dict[str, Any]:
    assert (await tools["create_sketch"]({"plane": plane}))["status"] == "success"
    square = {"x1": -5, "y1": -5, "x2": 5, "y2": 5}
    assert (await tools["add_rectangle"](square))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    return await tools["create_cut_extrude"]({"depth": 3, "end_condition": "Blind"})


@pytest.mark.asyncio
@pytest.mark.parametrize(("offset", "warned"), [(5.0, False), (7.5, True)])
async def test_a_cut_from_above_the_part_is_warned_about(
    scratch, offset: float, warned: bool
) -> None:
    tools = await _tools(scratch.adapter)
    assert (await scratch.adapter.create_part()).is_success
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    plate = {"x1": -20, "y1": -20, "x2": 20, "y2": 20}
    assert (await tools["add_rectangle"](plate))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    assert (await tools["create_extrusion"]({"depth": 5}))["status"] == "success"
    plane = await tools["create_reference_plane"](
        {"reference": "Top Plane", "offset": offset}
    )
    assert plane["status"] == "success", plane

    cut = await _square_cut(tools, plane["plane"]["name"])

    evidence(f"a 10 mm square cut 3 mm deep from {offset:g} mm up", cut)
    assert cut["status"] == "success", cut
    assert cut["cut_extrude"]["floor_area_mm2"] == pytest.approx(100.0, rel=1e-3)
    assert ("far less than its floor area" in (cut.get("warning") or "")) is warned
