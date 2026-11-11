"""``export_image`` with planes and sketches hidden, and a zoom box, on real SolidWorks.

From the Cellvis dish rack: pictures were cluttered with planes and sketches,
and a close-up needed a zoom set by hand. The pictures are left in the
evidence for a look: the first shows the block without its sketch or planes,
the second one corner of it, filling the picture.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_image_options.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks.visibility import DISPLAY_TOGGLES
from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.export import register_export_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("image-options-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_export_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


def _shown(model: Any) -> dict[str, bool]:
    ext = model.Extension
    return {
        name: bool(ext.GetUserPreferenceToggle(toggle, 0))
        for name, toggle in DISPLAY_TOGGLES.items()
    }


@pytest.mark.asyncio
async def test_a_clean_picture_and_a_close_up(scratch, tmp_path: Path) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    rect = {"x1": 0, "y1": 0, "x2": 40, "y2": 20}
    assert (await tools["add_rectangle"](rect))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    assert (await tools["create_extrusion"]({"depth": 10}))["status"] == "success"
    before = _shown(adapter.currentModel)
    clean, close = tmp_path / "clean.png", tmp_path / "corner.png"

    first = await tools["export_image"](
        {
            "file_path": str(clean),
            "view_orientation": "isometric",
            "hide": ["planes", "sketches", "origins"],
        }
    )
    second = await tools["export_image"](
        {
            "file_path": str(close),
            "view_orientation": "isometric",
            "zoom_box_mm": [0, 0, -5, 10, 10, 5],
        }
    )
    after = _shown(adapter.currentModel)

    evidence(
        "a picture without planes, sketch or origin, then one corner close up",
        {"clean": first, "close_up": second, "before": before, "after": after},
    )
    assert first["status"] == second["status"] == "success", (first, second)
    assert first["data"]["hidden"] == ["origins", "planes", "sketches"]
    assert clean.stat().st_size > 0 and close.stat().st_size > 0
    assert after == before
