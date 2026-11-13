"""The Cellvis gaps on real SolidWorks: placing components and print checks.

The spec scenarios of the change ``cellvis-assembly-and-print-checks``:

- ``set_component_transform``: a second block stacked 137 mm up; a block
  turned a quarter turn about Y; the first, fixed block moved back to the
  origin and still fixed; a component held by a mate reported, not moved
  silently; a first component inserted floating.
- ``check_printability``: a block printed flat is fine; a shelf's underside
  needs supports; a pocket open toward the plate is a suction cup, and not
  when printed the other way up; the user's STL options come back.

Positions are checked with ``IComponent2.GetBox``, the component's box in
assembly coordinates, not only with the transform the tool read back.

Scratch documents only, under pytest's ``tmp_path``. Collected only with
``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import stl_settings as stl
from tests.live.evidence import evidence


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.analysis import register_analysis_tools
    from solidworks_mcp.tools.export import register_export_tools
    from solidworks_mcp.tools.file_management import register_file_management_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("cellvis-gaps-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_file_management_tools(mcp, adapter, {})
    await register_export_tools(mcp, adapter, {})
    await register_analysis_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _sketch(
    tools: dict[str, Any], plane: str, draw: list[tuple[str, dict]]
) -> None:
    assert (await tools["create_sketch"]({"plane": plane}))["status"] == "success"
    for tool, arguments in draw:
        drawn = await tools[tool](arguments)
        assert drawn["status"] == "success", drawn
    assert (await tools["exit_sketch"]())["status"] == "success"


async def _block_part(scratch: Any, tools: dict[str, Any], path: Path) -> str:
    """A 20 x 10 x 6 block with its origin at a corner, saved to ``path``."""
    assert (await scratch.adapter.create_part()).is_success
    rect = {"x1": 0, "y1": 0, "x2": 20, "y2": 10}
    await _sketch(tools, "Front", [("add_rectangle", rect)])
    assert (await tools["create_extrusion"]({"depth": 6}))["status"] == "success"
    saved = await scratch.adapter.save_file(str(path))
    assert saved.is_success, saved.error
    scratch.written_files.append(str(path))
    return str(path)


def _boxes_mm(adapter: Any) -> dict[str, list[float]]:
    """Each top-level component's box in assembly coordinates, mm."""
    from solidworks_mcp.adapters import sw_type_info

    assembly = sw_type_info.flagged(adapter.currentModel, "IAssemblyDoc")
    out = {}
    for component in assembly.GetComponents(True):
        c = sw_type_info.flagged(component, "IComponent2")
        out[str(c.Name2)] = [
            round(float(v) * 1000, 3) + 0.0 for v in c.GetBox(False, False)
        ]
    return out


async def _two_blocks(
    scratch: Any, tools: dict[str, Any], tmp_path: Path, **first: Any
) -> str:
    part = await _block_part(scratch, tools, tmp_path / "cg_block.SLDPRT")
    assert (await scratch.adapter.create_assembly()).is_success
    scratch.written_files.append(str(tmp_path / "cg_asm.SLDASM"))
    one = await tools["insert_component"]({"file_path": part, **first})
    two = await tools["insert_component"]({"file_path": part, "x": 50})
    assert one["status"] == two["status"] == "success", (one, two)
    return part


# ---- set_component_transform -------------------------------------------------


@pytest.mark.asyncio
async def test_a_block_stacked_137_mm_up(scratch, tmp_path: Path) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _two_blocks(scratch, tools, tmp_path)

    reply = await tools["set_component_transform"](
        {"component": "cg_block-2", "origin_mm": [0, 137, 0]}
    )
    boxes = _boxes_mm(adapter)

    evidence("the second block 137 mm up", {"reply": reply, "boxes_mm": boxes})
    assert reply["status"] == "success", reply
    assert reply["placed"] is True
    assert reply["transform"]["origin_mm"] == pytest.approx([0.0, 137.0, 0.0])
    # The block is x 0..20, y 0..10, z 0..6 in its part (extruded along Z).
    assert boxes["cg_block-2"] == pytest.approx([0, 137, 0, 20, 147, 6], abs=1e-3)


@pytest.mark.asyncio
async def test_a_block_turned_a_quarter_turn_about_y(scratch, tmp_path: Path) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _two_blocks(scratch, tools, tmp_path)

    reply = await tools["set_component_transform"](
        {
            "component": "cg_block-2",
            "origin_mm": [10, 20, 30],
            "rotation_deg": [0, 90, 0],
        }
    )
    boxes = _boxes_mm(adapter)

    evidence("a quarter turn about Y", {"reply": reply, "boxes_mm": boxes})
    assert reply["placed"] is True
    assert reply["transform"]["rotation"][0] == pytest.approx(
        [0.0, 0.0, -1.0], abs=1e-9
    )
    # X (0..20) goes to -z, Y (0..10) stays, Z (0..6) goes to +x.
    assert boxes["cg_block-2"] == pytest.approx([10, 20, 10, 16, 30, 30], abs=1e-3)


@pytest.mark.asyncio
async def test_the_fixed_first_block_moves_back_to_the_origin(
    scratch, tmp_path: Path
) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _two_blocks(scratch, tools, tmp_path, x=10, y=10, z=10)

    reply = await tools["set_component_transform"](
        {"component": "cg_block-1", "origin_mm": [0, 0, 0]}
    )
    boxes = _boxes_mm(adapter)

    evidence("the fixed base back at the origin", {"reply": reply, "boxes_mm": boxes})
    assert (reply["placed"], reply["fixed"]) == (True, True)
    assert boxes["cg_block-1"] == pytest.approx([0, 0, 0, 20, 10, 6], abs=1e-3)


@pytest.mark.asyncio
async def test_a_first_component_can_be_inserted_floating(
    scratch, tmp_path: Path
) -> None:
    tools = await _tools(scratch.adapter)
    part = await _block_part(scratch, tools, tmp_path / "cg_float.SLDPRT")
    assert (await scratch.adapter.create_assembly()).is_success
    scratch.written_files.append(str(tmp_path / "cg_float_asm.SLDASM"))

    reply = await tools["insert_component"]({"file_path": part, "fixed": False})

    evidence("a floating first component", reply)
    assert reply["component"]["placement"]["fixed"] is False


@pytest.mark.asyncio
async def test_a_mated_component_is_reported_where_it_stays(
    scratch, tmp_path: Path
) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _two_blocks(scratch, tools, tmp_path)
    mate = await tools["add_mate"](
        {
            "component_a": "cg_block-1",
            "component_b": "cg_block-2",
            "entity_a": "Front Plane",
            "entity_b": "Front Plane",
            "mate_type": "coincident",
        }
    )
    assert mate["status"] == "success", mate

    reply = await tools["set_component_transform"](
        {"component": "cg_block-2", "origin_mm": [50, 0, 25]}
    )
    boxes = _boxes_mm(adapter)

    evidence(
        "move a mated block off its mate's plane", {"reply": reply, "boxes_mm": boxes}
    )
    assert reply["status"] == "success", reply
    assert reply["mates"] >= 1
    at = reply["transform"]["origin_mm"]
    assert boxes["cg_block-2"][:3] == pytest.approx(at, abs=1e-3)
    if reply["placed"] is False:
        assert "mate(s)" in reply["warning"]


# ---- check_printability ------------------------------------------------------


def _stl_options(app: Any) -> dict[str, Any]:
    return {
        "quality": app.GetUserPreferenceIntegerValue(stl.STL_QUALITY),
        "deviation": app.GetUserPreferenceDoubleValue(stl.STL_DEVIATION),
        "angle": app.GetUserPreferenceDoubleValue(stl.STL_ANGLE_TOLERANCE),
        "units": app.GetUserPreferenceIntegerValue(stl.STL_UNITS),
        "binary": app.GetUserPreferenceToggle(stl.STL_BINARY),
        "keep_coordinates": app.GetUserPreferenceToggle(stl.STL_KEEP_COORDINATES),
    }


@pytest.mark.asyncio
async def test_a_block_printed_flat_needs_nothing(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    rect = {"x1": -20, "y1": -10, "x2": 20, "y2": 10}
    await _sketch(tools, "Top", [("add_rectangle", rect)])
    assert (await tools["create_extrusion"]({"depth": 10}))["status"] == "success"
    before = _stl_options(adapter.swApp)

    reply = await tools["check_printability"]({"build_direction": "y"})
    after = _stl_options(adapter.swApp)

    evidence("a block on its base", {"reply": reply, "stl_options": [before, after]})
    assert reply["status"] == "success", reply
    assert reply["data"]["ok"] is True
    assert reply["data"]["down_facing"]["needs_support_mm2"] == 0.0
    assert after == before


@pytest.mark.asyncio
async def test_a_shelf_needs_supports_under_it(scratch) -> None:
    """A post 10 x 20 high with a 10 mm shelf at 8..10 mm, 20 mm deep."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    corners = [(0, 0), (10, 0), (10, 8), (20, 8), (20, 10), (10, 10), (10, 20), (0, 20)]
    lines = [
        ("add_line", {"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        for (x1, y1), (x2, y2) in zip(corners, [*corners[1:], corners[0]], strict=True)
    ]
    await _sketch(tools, "Front", lines)
    assert (await tools["create_extrusion"]({"depth": 20}))["status"] == "success"

    reply = await tools["check_printability"]({"build_direction": "y"})

    evidence("a shelf 8 mm up", reply)
    data = reply["data"]
    assert data["down_facing"]["needs_support_mm2"] == pytest.approx(200.0, rel=1e-3)
    assert data["islands"]["count"] == 0
    assert data["suction_cups"]["count"] == 0
    assert data["ok"] is False


@pytest.mark.asyncio
async def test_a_pocket_open_toward_the_plate_is_a_suction_cup(scratch) -> None:
    """A 30 mm cube with a 20 x 20 x 15 pocket open on its bottom face."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _sketch(
        tools, "Top", [("add_rectangle", {"x1": -15, "y1": -15, "x2": 15, "y2": 15})]
    )
    assert (await tools["create_extrusion"]({"depth": 30}))["status"] == "success"
    await _sketch(
        tools, "Top", [("add_rectangle", {"x1": -10, "y1": -10, "x2": 10, "y2": 10})]
    )
    cut = await tools["create_cut_extrude"]({"depth": 15})
    assert cut["status"] == "success", cut

    upright = await tools["check_printability"]({"build_direction": "y"})
    flipped = await tools["check_printability"]({"build_direction": "-y"})

    evidence("a bottom pocket, both ways up", {"upright": upright, "flipped": flipped})
    cups = upright["data"]["suction_cups"]
    assert cups["count"] == 1
    assert cups["items"][0]["depth_mm"] == pytest.approx(15.0, abs=0.05)
    assert cups["items"][0]["opening_area_mm2"] == pytest.approx(400.0, rel=1e-3)
    assert flipped["data"]["suction_cups"]["count"] == 0
