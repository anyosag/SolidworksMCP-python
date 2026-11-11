"""A long operation stops at its time limit, on real SolidWorks.

From the Cellvis dish rack: a client killed mid-fillet left SolidWorks at
100% CPU walking edges for nobody. Loops of many COM calls now stop between
calls once their operation runs past ``SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS``.
Here a 400-segment outline with a 0.2 s limit stops part-way, removes what it
drew, and the next call runs normally.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_long_operations.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("long-operations-live")
    await register_sketching_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


def _polygon(corners: int, radius: float) -> list[list[float]]:
    return [
        [
            radius * math.cos(2 * math.pi * i / corners),
            radius * math.sin(2 * math.pi * i / corners),
        ]
        for i in range(corners)
    ]


@pytest.mark.asyncio
async def test_an_outline_past_its_limit_stops_and_cleans_up(
    scratch, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = await _tools(scratch.adapter)
    assert (await scratch.adapter.create_part()).is_success
    assert (await tools["create_sketch"]({"plane": "Front"}))["status"] == "success"
    monkeypatch.setenv("SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS", "0.2")

    stopped = await tools["add_outlines"]({"outlines": [{"points": _polygon(400, 30)}]})
    monkeypatch.delenv("SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS")
    small = await tools["add_outlines"]({"outlines": [{"points": _polygon(6, 5)}]})

    evidence("400 segments with a 0.2 s limit, then a hexagon", {"stopped": stopped})
    assert stopped["error_type"] == "operation_stopped", stopped
    assert "segments this call drew were removed again" in stopped["message"]
    assert small["status"] == "success", small
    assert small["segment_count"] == 6
