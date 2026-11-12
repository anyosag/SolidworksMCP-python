"""The Cellvis DishRack build's bug reports, fixed, on real SolidWorks.

- ``insert_component``: a part whose box centre is off its origin lands with
  its origin at the point asked (``AddComponent4`` places the centre).
- ``activate_document``: a part the assembly loaded, with no window of its
  own, is opened and activated.
- ``export_image``: ``zoom_box_mm`` in the right view is turned into the
  view's coordinates (``ViewZoomTo2`` takes those).
- ``edit_feature``: an Instant3D boss reports ``Extrusion``, a cut ``Cut``;
  ``list_features`` lists them so, and leaves out the standard folders.
- ``select_edges``: ``any_of`` takes edges in two places in one call.
- ``export_stl``: an assembly is one file, closed, of the right size, and the
  user's "one file" option is put back; a part's mesh volume matches it.
- ``delete_sketch_entities``: ``all`` empties an open sketch.
- ``check_wall_thickness``: a box around the thin floor excludes it.
- ``execute_workflow``: a step's ``document`` runs on that document.

Scratch documents only, saved under pytest's ``tmp_path``. Collected only
with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from tests.live.evidence import evidence

#: swUserPreferenceToggle_e.swSTLComponentsIntoOneFile (SolidWorks 2026).
_STL_ONE_FILE = 72


async def _tools(adapter: Any) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.analysis import register_analysis_tools
    from solidworks_mcp.tools.automation import register_automation_tools
    from solidworks_mcp.tools.export import register_export_tools
    from solidworks_mcp.tools.file_management import register_file_management_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("dishrack-fixes-live")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_file_management_tools(mcp, adapter, {})
    await register_export_tools(mcp, adapter, {})
    await register_analysis_tools(mcp, adapter, {})
    await register_automation_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _box(
    tools: dict[str, Any], plane: str, rect: dict[str, float], depth: float
) -> dict[str, Any]:
    """A rectangle on ``plane`` extruded ``depth`` mm; the extrusion reply."""
    assert (await tools["create_sketch"]({"plane": plane}))["status"] == "success"
    drawn = await tools["add_rectangle"](rect)
    assert drawn["status"] == "success", drawn
    assert (await tools["exit_sketch"]())["status"] == "success"
    boss = await tools["create_extrusion"]({"depth": depth})
    assert boss["status"] == "success", boss
    return boss


async def _off_centre_part(scratch: Any, tools: dict[str, Any], path: Path) -> str:
    """A 20 x 10 x 6 mm block in one corner of its origin, saved to ``path``.

    On the Front plane x 0..20, y 0..10, extruded 6 mm: its box centre is
    (10, 5, ±3) mm, its origin a corner.
    """
    assert (await scratch.adapter.create_part()).is_success
    await _box(tools, "Front", {"x1": 0, "y1": 0, "x2": 20, "y2": 10}, 6.0)
    saved = await scratch.adapter.save_file(str(path))
    assert saved.is_success, saved.error
    scratch.written_files.append(str(path))
    return str(path)


def _origins_mm(adapter: Any) -> dict[str, list[float]]:
    """Each top-level component's origin in the assembly, mm."""
    from solidworks_mcp.adapters import sw_type_info

    assembly = sw_type_info.flagged(adapter.currentModel, "IAssemblyDoc")
    out = {}
    for component in assembly.GetComponents(True):
        c = sw_type_info.flagged(component, "IComponent2")
        data = list(c.Transform2.ArrayData)
        out[str(c.Name2)] = [round(v * 1000, 4) + 0.0 for v in data[9:12]]
    return out


@pytest.mark.asyncio
async def test_a_component_lands_with_its_origin_where_asked(
    scratch, tmp_path: Path
) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    part = await _off_centre_part(scratch, tools, tmp_path / "df_corner.SLDPRT")
    assert (await adapter.create_assembly()).is_success
    scratch.written_files.append(str(tmp_path / "df_corner_asm.SLDASM"))

    first = await tools["insert_component"]({"file_path": part})
    second = await tools["insert_component"](
        {"file_path": part, "x": 50, "y": 0, "z": 10}
    )
    origins = _origins_mm(adapter)

    evidence(
        "two copies of a corner-origin block, at (0, 0, 0) and (50, 0, 10) mm",
        {"first": first, "second": second, "origins_mm": origins},
    )
    assert first["status"] == second["status"] == "success", (first, second)
    assert "warning" not in first and "warning" not in second
    assert first["component"]["placement"]["placed"] is True
    assert second["component"]["placement"]["placed"] is True
    assert sorted(origins.values()) == [[0.0, 0.0, 0.0], [50.0, 0.0, 10.0]]


@pytest.mark.asyncio
async def test_a_part_loaded_only_by_its_assembly_is_opened_and_activated(
    scratch, tmp_path: Path
) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    part = await _off_centre_part(scratch, tools, tmp_path / "df_loaded.SLDPRT")
    assert (await adapter.create_assembly()).is_success
    scratch.written_files.append(str(tmp_path / "df_loaded_asm.SLDASM"))
    assert (await tools["insert_component"]({"file_path": part}))["status"] == "success"
    # Close the part's window: the assembly keeps it loaded, windowless.
    # (Reopening a saved assembly instead set off a SOLIDWORKS CAM dialog
    # about lightweight parts on this install.)
    assert (await adapter.activate_document("df_loaded.SLDPRT")).is_success
    assert (await adapter.close_model()).is_success
    loaded = [
        (str(adapter._get_attr_or_call(d, "GetTitle")), d.Visible)
        for d in adapter.swApp.GetDocuments() or []
        if "df_loaded" in str(adapter._get_attr_or_call(d, "GetTitle")).lower()
    ]

    result = await tools["activate_document"]({"title_or_path": "df_loaded"})
    info = await adapter.get_model_info()

    evidence(
        "activate the part the assembly loaded",
        {"loaded": loaded, "result": result, "info": info.data},
    )
    assert loaded and all(visible is False for _title, visible in loaded), loaded
    assert result["status"] == "success", result
    assert (result.get("data") or result).get("opened_window") is True
    assert "df_loaded" in str((info.data or {}).get("title", "")).lower()


@pytest.mark.asyncio
async def test_a_zoom_box_in_the_right_view_is_in_view_coordinates(
    scratch, tmp_path: Path
) -> None:
    """The +X end of a 40 x 20 x 12 block, close up from the right."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _box(tools, "Front", {"x1": -20, "y1": -10, "x2": 20, "y2": 10}, 12.0)
    front, right = tmp_path / "front.png", tmp_path / "right.png"
    box = [15, 0, 0, 20, 10, 12]

    in_front = await tools["export_image"](
        {"file_path": str(front), "view_orientation": "front", "zoom_box_mm": box}
    )
    in_right = await tools["export_image"](
        {"file_path": str(right), "view_orientation": "right", "zoom_box_mm": box}
    )
    # The whole +X face (z -6..6, y -10..10): it should come out centred.
    face = tmp_path / "right_face.png"
    whole_face = await tools["export_image"](
        {
            "file_path": str(face),
            "view_orientation": "right",
            "zoom_box_mm": [19, -10, -6, 20, 10, 6],
        }
    )
    view = adapter.currentModel.ActiveView
    orientation = list(view.Orientation3.ArrayData)
    translation = list(view.Translation3.ArrayData)
    kept = Path(__file__).parents[1] / ".generated" / "dishrack_fixes"
    kept.mkdir(parents=True, exist_ok=True)
    for picture in (front, right, face):
        if picture.exists():
            shutil.copy(picture, kept / picture.name)

    evidence(
        "the same model box zoomed in the front and the right view",
        {
            "front": in_front.get("data"),
            "right": in_right.get("data"),
            "face": whole_face.get("data"),
            "orientation3": orientation,
            "translation3": translation,
            "kept": str(kept),
        },
    )
    assert in_front["status"] == in_right["status"] == "success", (in_front, in_right)
    front_box = in_front["data"]["zoom_box_view_mm"]
    right_box = in_right["data"]["zoom_box_view_mm"]
    assert front_box == pytest.approx(box, abs=1e-6)
    # Right view: screen x is model z (either sign), y stays, depth is model x.
    widths = [right_box[i + 3] - right_box[i] for i in range(3)]
    assert widths == pytest.approx([12.0, 10.0, 5.0], abs=1e-6)
    assert right_box[1] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.asyncio
async def test_an_instant3d_boss_and_cut_name_their_types(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    boss = await _box(tools, "Top", {"x1": -20, "y1": -15, "x2": 20, "y2": 15}, 10.0)
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    circle = {"center_x": 0, "center_y": 0, "radius": 3}
    assert (await tools["add_circle"](circle))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    cut = await tools["create_cut_extrude"]({"depth": 4.0})
    assert cut["status"] == "success", cut

    boss_edit = await tools["edit_feature"](
        {"name": boss["extrusion"]["name"], "depth": 12}
    )
    cut_edit = await tools["edit_feature"](
        {"name": cut["cut_extrude"]["name"], "depth": 5}
    )

    evidence("edit a boss and a cut", {"boss": boss_edit, "cut": cut_edit})
    assert boss_edit["status"] == cut_edit["status"] == "success", (boss_edit, cut_edit)
    assert boss_edit["data"]["type"] == "Extrusion"
    assert cut_edit["data"]["type"] == "Cut"


@pytest.mark.asyncio
async def test_edges_in_two_places_in_one_select_edges_call(scratch) -> None:
    """The block's two upright edges at x = +20, front and back, in one call."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    boss = await _box(tools, "Front", {"x1": -20, "y1": -10, "x2": 20, "y2": 10}, 12.0)
    name = boss["extrusion"]["name"]
    rules = [
        {"inside_box": [[19, 9, -1], [21, 11, 13]], "parallel_to": "z"},
        {"inside_box": [[19, -11, -1], [21, -9, 13]], "parallel_to": "z"},
    ]

    started = time.perf_counter()
    together = await tools["select_edges"]({"feature": name, "any_of": rules})
    one_call = time.perf_counter() - started
    started = time.perf_counter()
    for index, rule in enumerate(rules):
        alone = await tools["select_edges"](
            {"feature": name, **rule, "append": index > 0}
        )
        assert alone["status"] == "success", alone
    two_calls = time.perf_counter() - started

    evidence(
        "two upright edges in one any_of call, then one call each",
        {"any_of": together, "seconds": {"one": one_call, "two": two_calls}},
    )
    assert together["status"] == "success", together
    assert together["data"]["selected_edges"] == 2
    assert len(together["data"]["matched"]["rules"]) == 2
    assert alone["data"]["selection_count"] == 2


@pytest.mark.asyncio
async def test_list_features_names_instant3d_types_and_drops_the_folders(
    scratch,
) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _box(tools, "Top", {"x1": -20, "y1": -15, "x2": 20, "y2": 15}, 10.0)
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    circle = {"center_x": 0, "center_y": 0, "radius": 3}
    assert (await tools["add_circle"](circle))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    assert (await tools["create_cut_extrude"]({"depth": 4.0}))["status"] == "success"

    everything = await tools["list_features"]({})
    own = await tools["list_features"]({"include_standard": False})
    cuts = await tools["list_features"]({"types": ["cut"]})
    newest = await tools["list_features"]({"last": 1})

    evidence(
        "the tree, without the standard items, the cuts and the newest",
        {
            "all": [(f["name"], f["type"]) for f in everything["features"]],
            "own": [(f["name"], f["type"]) for f in own["features"]],
            "cuts": cuts["features"],
            "newest": newest["features"],
        },
    )
    types = {f["name"]: f["type"] for f in everything["features"]}
    assert "ICE" not in types.values(), types
    assert [f["type"] for f in own["features"]] == [
        "ProfileFeature",
        "Extrusion",
        "ProfileFeature",
        "Cut",
    ]
    assert [f["type"] for f in cuts["features"]] == ["Cut"]
    assert [f["type"] for f in newest["features"]] == ["Cut"]
    assert "assembly_tree" not in everything


async def _two_block_assembly(
    scratch: Any, tools: dict[str, Any], folder: Path
) -> Path:
    """Two 20 x 10 x 6 blocks, 50 mm apart in x, in a saved assembly."""
    adapter = scratch.adapter
    part = await _off_centre_part(scratch, tools, folder / "df_stl_block.SLDPRT")
    assembly = folder / "df_stl_asm.SLDASM"
    assert (await adapter.create_assembly()).is_success
    for x in (0, 50):
        placed = await tools["insert_component"]({"file_path": part, "x": x})
        assert placed["status"] == "success", placed
    saved = await adapter.save_file(str(assembly))
    assert saved.is_success, saved.error
    scratch.written_files.append(str(assembly))
    return assembly


@pytest.mark.asyncio
async def test_an_assembly_exports_to_one_closed_stl(scratch, tmp_path: Path) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _two_block_assembly(scratch, tools, tmp_path)
    one_file_before = adapter.swApp.GetUserPreferenceToggle(_STL_ONE_FILE)
    target = tmp_path / "df_stl_asm.stl"

    result = await tools["export_stl"]({"file_path": str(target)})
    one_file_after = adapter.swApp.GetUserPreferenceToggle(_STL_ONE_FILE)
    split = sorted(p.name for p in tmp_path.glob("df_stl_asm - *"))

    evidence(
        "an assembly of two blocks to one STL",
        {
            "result": result,
            "split_files": split,
            "one_file": [one_file_before, one_file_after],
        },
    )
    assert result["status"] == "success", result
    assert target.exists() and split == []
    check = result["export"]["mesh_check"]
    assert check["closed"] is True, check
    assert check["triangles"] >= 24  # two boxes, 12 triangles each
    assert check["volume_mm3"] == pytest.approx(2 * 1200.0, rel=1e-3)
    assert check["size_mm"] == pytest.approx([70.0, 10.0, 6.0], abs=1e-3)
    assert one_file_after == one_file_before


@pytest.mark.asyncio
async def test_a_parts_stl_volume_matches_the_part(scratch, tmp_path: Path) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    await _box(tools, "Front", {"x1": 0, "y1": 0, "x2": 20, "y2": 10}, 6.0)
    target = tmp_path / "df_block.stl"

    result = await tools["export_stl"]({"file_path": str(target), "units": "in"})

    evidence("a 1200 mm³ block written in inches", result)
    assert result["status"] == "success", result
    check = result["export"]["mesh_check"]
    assert check["units"] == "in"
    assert check["closed"] is True
    assert check["volume_mm3"] == pytest.approx(1200.0, rel=1e-3)
    assert check["cad_volume_mm3"] == pytest.approx(1200.0, rel=1e-4)
    assert check["volume_ratio"] == pytest.approx(1.0, rel=1e-3)


@pytest.mark.asyncio
async def test_a_whole_sketch_is_emptied(scratch) -> None:
    adapter = scratch.adapter
    tools = await _tools(adapter)
    assert (await adapter.create_part()).is_success
    sketch = await tools["create_sketch"]({"plane": "Front"})
    assert sketch["status"] == "success", sketch
    rect = {"x1": 0, "y1": 0, "x2": 20, "y2": 10}
    assert (await tools["add_rectangle"](rect))["status"] == "success"
    assert (await tools["add_circle"]({"center_x": 30, "center_y": 5, "radius": 3}))[
        "status"
    ] == "success"
    closed = await tools["exit_sketch"]()
    name = str((closed.get("sketch") or sketch["sketch"])["name"])

    opened = await tools["edit_sketch"]({"name": name})
    emptied = await tools["delete_sketch_entities"]({"all": True})
    stale = await tools["delete_sketch_entities"]({"ids": ["Line_9"]})
    # SolidWorks deletes a sketch exited empty (live, 2026-11-12): draw the
    # replacement first.
    redrawn = await tools["add_circle"]({"center_x": 5, "center_y": 5, "radius": 2})
    first_exit = await tools["exit_sketch"]()
    reopened = await tools["edit_sketch"]({"name": name})
    second_exit = await tools["exit_sketch"]()

    evidence(
        "a rectangle and a circle, delete all, then one new circle",
        {
            "opened": opened,
            "emptied": emptied,
            "stale": stale,
            "exits": [first_exit, second_exit],
            "reopened": reopened,
        },
    )
    assert len(opened["sketch"]["segments"]) == 5
    assert emptied["status"] == "success", emptied
    assert emptied.get("deleted_count", len(emptied["deleted"])) == 5
    assert stale["status"] == "error"
    assert redrawn["status"] == first_exit["status"] == "success", first_exit
    assert reopened["status"] == second_exit["status"] == "success", reopened
    assert [s["type"] for s in reopened["sketch"]["segments"]] == ["arc"]


@pytest.mark.asyncio
async def test_a_box_around_the_thin_floor_excludes_it(scratch) -> None:
    from tests.live.test_live_sw_wall_thickness import _plate_with_pocket

    adapter = scratch.adapter
    tools = await _tools(adapter)
    await _plate_with_pocket(adapter, tools)

    strict = await tools["check_wall_thickness"]({"min_wall_mm": 1.2})
    excused = await tools["check_wall_thickness"](
        {"min_wall_mm": 1.2, "exclude_boxes_mm": [[-11, -1, -6, 11, 2, 6]]}
    )

    evidence(
        "the 1 mm floor, checked, then excluded", {"strict": strict, "excused": excused}
    )
    assert strict["status"] == excused["status"] == "success", (strict, excused)
    assert strict["data"]["ok"] is False
    assert excused["data"]["ok"] is True, excused
    assert excused["data"]["excluded"]["below_minimum"] > 0


@pytest.mark.asyncio
async def test_a_workflow_step_runs_on_the_document_it_names(
    scratch, tmp_path: Path
) -> None:
    """Two parts open; the active one (30 mm long) is not the one named (20)."""
    adapter = scratch.adapter
    tools = await _tools(adapter)
    first = await _off_centre_part(scratch, tools, tmp_path / "df_flow_a.SLDPRT")
    second = tmp_path / "df_flow_b.SLDPRT"
    assert (await adapter.create_part()).is_success
    await _box(tools, "Front", {"x1": 0, "y1": 0, "x2": 30, "y2": 10}, 6.0)
    assert (await adapter.save_file(str(second))).is_success
    scratch.written_files.append(str(second))
    target = tmp_path / "df_flow_a.stl"

    result = await tools["execute_workflow"](
        {
            "detail": "full",
            "steps": [
                {
                    "tool": "export_stl",
                    "arguments": {"input_data": {"file_path": str(target)}},
                    "document": Path(first).name,
                },
            ],
        }
    )

    evidence("export the inactive part's STL by name", result)
    assert result["status"] == "success", result
    check = result["steps"][0]["result"]["export"]["mesh_check"]
    assert check["size_mm"] == pytest.approx([20.0, 10.0, 6.0], abs=1e-3)
    assert target.exists()
