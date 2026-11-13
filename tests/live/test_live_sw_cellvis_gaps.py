"""The Cellvis gaps on real SolidWorks: placing components and print checks.

The spec scenarios of the change ``cellvis-assembly-and-print-checks``:

- ``set_component_transform``: a second block stacked 137 mm up; a block
  turned a quarter turn about Y; the first, fixed block moved back to the
  origin and still fixed; a component held by a mate reported, not moved
  silently; a first component inserted floating.
- ``check_printability``: a block printed flat is fine; a shelf's underside
  needs supports; a pocket open toward the plate is a suction cup, and not
  when printed the other way up; the user's STL options come back.
- ``measure_clearance``: a Ø9.5 pin in a Ø10 hole and a 4.0 tongue in a 4.5
  slot are 0.25 mm clear; blocks overlapping 1 mm touch.
- ``export_image`` with ``section``: the assembly cut on Front Plane, and the
  section gone afterwards.
- ``edit_feature`` with edges: a fillet broken by a sketch edit repaired in
  place; a chamfer moved to other edges by a rule.

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


# ---- measure_clearance and section pictures ----------------------------------


async def _fit_assembly(scratch: Any, tools: dict[str, Any], folder: Path) -> None:
    """A plate with a Ø10 hole and a 4.5 slot; a Ø9.5 pin and a 4.0 tongue in them.

    Sketches on Top are model (x, -z): the hole is at x 15, the slot centred
    at x -12.5; the pin and tongue run along Y through the 10 mm plate.
    """
    adapter = scratch.adapter

    async def part(name: str, build: list[tuple[str, dict, float, bool]]) -> str:
        assert (await adapter.create_part()).is_success
        for tool, shape, depth, cut in build:
            await _sketch(tools, "Top", [(tool, shape)])
            made = await tools["create_cut_extrude" if cut else "create_extrusion"](
                {"depth": depth, "end_condition": "ThroughAllBoth"}
                if cut
                else {"depth": depth}
            )
            assert made["status"] == "success", made
        path = folder / f"cg_{name}.SLDPRT"
        assert (await adapter.save_file(str(path))).is_success
        scratch.written_files.append(str(path))
        return str(path)

    plate = await part(
        "plate",
        [
            ("add_rectangle", {"x1": -30, "y1": -20, "x2": 30, "y2": 20}, 10, False),
            ("add_circle", {"center_x": 15, "center_y": 0, "radius": 5}, 10, True),
            (
                "add_rectangle",
                {"x1": -20, "y1": -2.25, "x2": -5, "y2": 2.25},
                10,
                True,
            ),
        ],
    )
    pin = await part(
        "pin",
        [("add_circle", {"center_x": 0, "center_y": 0, "radius": 4.75}, 30, False)],
    )
    tongue = await part(
        "tongue",
        [("add_rectangle", {"x1": -5, "y1": -2, "x2": 5, "y2": 2}, 30, False)],
    )
    assert (await adapter.create_assembly()).is_success
    scratch.written_files.append(str(folder / "cg_fit.SLDASM"))
    for path, origin in (
        (plate, (0, 0, 0)),
        (pin, (15, -10, 0)),
        (tongue, (-12.5, -10, 0)),
    ):
        x, y, z = origin
        placed = await tools["insert_component"](
            {"file_path": path, "x": x, "y": y, "z": z}
        )
        assert placed["status"] == "success", placed


@pytest.mark.asyncio
async def test_a_pin_and_a_tongue_are_a_quarter_millimetre_clear(
    scratch, tmp_path: Path
) -> None:
    tools = await _tools(scratch.adapter)
    await _fit_assembly(scratch, tools, tmp_path)

    pin = await tools["measure_clearance"](
        {"component_a": "cg_pin-1", "component_b": "cg_plate-1"}
    )
    tongue = await tools["measure_clearance"](
        {"component_a": "cg_tongue-1", "component_b": "cg_plate-1"}
    )

    evidence("a pin in a hole and a tongue in a slot", {"pin": pin, "tongue": tongue})
    for reply in (pin, tongue):
        assert reply["status"] == "success", reply
        assert reply["data"]["clearance_mm"] == pytest.approx(0.25, abs=1e-3)
        assert reply["data"]["touching"] is False
        a, b = reply["data"]["point_a_mm"], reply["data"]["point_b_mm"]
        gap = sum((p - q) ** 2 for p, q in zip(a, b, strict=True)) ** 0.5
        assert gap == pytest.approx(0.25, abs=1e-3)
    # On the cylinders, not their axes.
    assert pin["data"]["face_a"]["kind"] == "cylinder"


@pytest.mark.asyncio
async def test_blocks_overlapping_touch(scratch, tmp_path: Path) -> None:
    tools = await _tools(scratch.adapter)
    part = await _block_part(scratch, tools, tmp_path / "cg_overlap.SLDPRT")
    assert (await scratch.adapter.create_assembly()).is_success
    scratch.written_files.append(str(tmp_path / "cg_overlap_asm.SLDASM"))
    for x in (0, 19):
        placed = await tools["insert_component"]({"file_path": part, "x": x})
        assert placed["status"] == "success", placed

    reply = await tools["measure_clearance"](
        {"component_a": "cg_overlap-1", "component_b": "cg_overlap-2"}
    )

    evidence("two blocks 1 mm into each other", reply)
    assert reply["data"]["clearance_mm"] == 0
    assert reply["data"]["touching"] is True
    assert "check_interference" in reply["warning"]


@pytest.mark.asyncio
async def test_a_section_picture_and_no_section_afterwards(
    scratch, tmp_path: Path
) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _fit_assembly(scratch, tools, tmp_path)
    kept = Path(__file__).parents[1] / ".generated" / "cellvis_gaps"
    kept.mkdir(parents=True, exist_ok=True)
    cut, plain = kept / "section_cut.png", kept / "section_after.png"

    sectioned = await tools["export_image"](
        {
            "file_path": str(cut),
            "view_orientation": "front",
            "section": {"plane": "Front Plane", "offset_mm": 0},
        }
    )
    after = await tools["export_image"](
        {"file_path": str(plain), "view_orientation": "front"}
    )
    unknown = await tools["export_image"](
        {"file_path": str(kept / "x.png"), "section": {"plane": "Plane99"}}
    )

    evidence(
        "the fit cut on Front Plane, then a plain picture",
        {"sectioned": sectioned, "after": after, "unknown": unknown, "kept": str(kept)},
    )
    assert sectioned["status"] == "success", sectioned
    assert sectioned["data"]["section"]["removed"] is True
    assert "warning" not in sectioned or "section" not in sectioned["warning"]
    assert after["status"] == "success", after
    assert cut.read_bytes() != plain.read_bytes()
    assert unknown["error_type"] == "not_found"


# ---- fillet and chamfer edges --------------------------------------------------


@pytest.mark.asyncio
async def test_a_fillet_broken_by_a_sketch_edit_is_repaired_in_place(scratch) -> None:
    """An L-shaped block filleted on its inner corner, redrawn as a rectangle."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    corners = [(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)]
    lines = [
        ("add_line", {"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        for (x1, y1), (x2, y2) in zip(corners, [*corners[1:], corners[0]], strict=True)
    ]
    sketch = await tools["create_sketch"]({"plane": "Top"})
    name = str(sketch["sketch"]["name"])
    for tool, arguments in lines:
        assert (await tools[tool](arguments))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    assert (await tools["create_extrusion"]({"depth": 10}))["status"] == "success"
    # The inner corner's upright edge: sketch (10, 10) is model (10, y, -10).
    corner = {"parallel_to": "y", "inside_box": [[9, -1, -11], [11, 11, -9]]}
    assert (await tools["select_edges"](corner))["status"] == "success"
    fillet = await tools["add_fillet"]({"radius": 2.0, "edge_names": []})
    fillet_name = str(fillet["fillet"]["name"])
    order = [f["name"] for f in (await tools["list_features"]({}))["features"]]
    assert (await tools["edit_sketch"]({"name": name}))["status"] == "success"
    assert (await tools["delete_sketch_entities"]({"all": True}))["status"] == "success"
    rect = {"x1": 0, "y1": 0, "x2": 30, "y2": 30}
    assert (await tools["add_rectangle"](rect))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    broken = await tools["rebuild_model"]({})
    # An upright edge of the rectangle, at sketch (30, 30): model (30, y, -30).
    upright = {"parallel_to": "y", "inside_box": [[29, -1, -31], [31, 11, -29]]}
    assert (await tools["select_edges"](upright))["status"] == "success"

    repaired = await tools["edit_feature"]({"name": fillet_name, "edges": "selection"})
    rebuilt = await tools["rebuild_model"]({})
    after = [f["name"] for f in (await tools["list_features"]({}))["features"]]

    evidence(
        "the fillet's edge gone, then a new one",
        {"broken": broken, "repaired": repaired, "rebuilt": rebuilt},
    )
    assert broken["status"] == "error"
    assert repaired["status"] == "success", repaired
    assert repaired["data"]["edges_after"] == 1
    assert rebuilt["status"] == "success", rebuilt
    assert after.index(fillet_name) == order.index(fillet_name)


@pytest.mark.asyncio
async def test_a_chamfer_moved_to_other_edges_by_a_rule(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    rect = {"x1": -20, "y1": -15, "x2": 20, "y2": 15}
    await _sketch(tools, "Top", [("add_rectangle", rect)])
    assert (await tools["create_extrusion"]({"depth": 10}))["status"] == "success"
    edge = {"side": "+y", "inside_box": [[-21, 9, 14], [21, 11, 16]]}
    assert (await tools["select_edges"](edge))["status"] == "success"
    chamfer = await tools["add_chamfer"]({"distance": 1.0, "edge_names": []})
    assert chamfer["status"] == "success", chamfer
    name = str(chamfer["chamfer"]["name"])

    # The bottom face's four straight edges: none of them made by the chamfer.
    moved = await tools["edit_feature"](
        {"name": name, "edge_rules": {"side": "-y", "edge_type": "linear"}}
    )
    rebuilt = await tools["rebuild_model"]({})

    evidence(
        "a chamfer moved to the bottom edges", {"moved": moved, "rebuilt": rebuilt}
    )
    assert moved["status"] == "success", moved
    assert (moved["data"]["edges_before"], moved["data"]["edges_after"]) == (1, 4)
    assert rebuilt["status"] == "success", rebuilt
