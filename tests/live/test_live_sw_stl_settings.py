"""``export_stl`` mesh settings for one file, on real SolidWorks.

From the Cellvis dish rack: printing needed a finer mesh than the user's STL
options. A custom 0.005 mm deviation must give more facets than coarse, the
file must be in the units asked for, and the user's options must be the same
afterwards.

The SolidWorks help gives no unit for ``swSTLDeviation`` and
``swSTLAngleTolerance``; the adapter writes metres and radians. The evidence
records the user's raw values before the export, which shows which unit
SolidWorks stores (an angle near 0.17 is radians, near 10 degrees).

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_stl_settings.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import stl_settings as stl
from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.export import register_export_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("stl-settings-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_export_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


def _preferences(app: Any) -> dict[str, Any]:
    return {
        "quality": app.GetUserPreferenceIntegerValue(stl.STL_QUALITY),
        "deviation": app.GetUserPreferenceDoubleValue(stl.STL_DEVIATION),
        "angle": app.GetUserPreferenceDoubleValue(stl.STL_ANGLE_TOLERANCE),
        "units": app.GetUserPreferenceIntegerValue(stl.STL_UNITS),
        "binary": app.GetUserPreferenceToggle(stl.STL_BINARY),
    }


def _triangles(path: Path) -> int:
    """The facet count of a binary STL (the 4 bytes after its 80-byte header)."""
    return int(struct.unpack("<I", path.read_bytes()[80:84])[0])


@pytest.mark.asyncio
async def test_a_finer_mesh_for_one_file_leaves_the_users_options(
    scratch, tmp_path: Path
) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    circle = {"center_x": 0, "center_y": 0, "radius": 20}
    assert (await tools["add_circle"](circle))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    assert (await tools["create_extrusion"]({"depth": 10}))["status"] == "success"
    before = _preferences(adapter.swApp)
    coarse, fine = tmp_path / "coarse.stl", tmp_path / "fine.stl"
    scratch.written_files += [str(coarse), str(fine)]

    rough = await tools["export_stl"](
        {"file_path": str(coarse), "resolution": "coarse", "binary": True}
    )
    smooth = await tools["export_stl"](
        {
            "file_path": str(fine),
            "deviation_mm": 0.005,
            "angle_deg": 2,
            "units": "mm",
            "binary": True,
        }
    )
    after = _preferences(adapter.swApp)

    evidence(
        "coarse vs a 0.005 mm / 2 degree mesh of a 40 mm disc",
        {
            "user_options_before": before,
            "user_options_after": after,
            "coarse": rough,
            "fine": smooth,
            "triangles": {"coarse": _triangles(coarse), "fine": _triangles(fine)},
        },
    )
    assert rough["status"] == smooth["status"] == "success", (rough, smooth)
    assert smooth["export"]["mesh"]["restored"] is True
    assert _triangles(fine) > 2 * _triangles(coarse)
    assert after == before
