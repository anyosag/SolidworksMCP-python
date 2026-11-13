"""Probe section views in pictures, and replacing a fillet's or chamfer's edges.

Task 1.2 of the ``cellvis-assembly-and-print-checks`` OpenSpec change. On
scratch parts made through ``PyWin32Adapter`` it records:

* **Section:** a picture, then ``IModelViewManager.CreateSectionView`` with
  ``ISectionViewData`` on Front Plane, a picture, then
  ``IModelViewManager.RemoveSectionView``, a picture. The pictures are
  compared pixel by pixel: the first and last should match, the middle not.
* **Fillet edges:** a 40 x 30 x 10 block with a 1 mm fillet on one top edge;
  its definition's ``Edges`` put to the top face's four edges through late
  binding; the edge count and volume before and after.
* **Chamfer edges:** the same with a chamfer.
* **A broken fillet:** an L-shaped block filleted on its inner corner; the
  sketch redrawn as a plain rectangle, so the edge is gone and the fillet
  fails; then its ``Edges`` put to one of the rectangle's upright edges, and
  whether it rebuilds.

It only touches documents it creates. The report and pictures stay in
``tests/.generated/probe_section_fillet/``.

Usage (SolidWorks running, nothing else driving it, the user's OK)::

    .venv\\Scripts\\python.exe tests/scripts/probe_section_fillet.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from solidworks_mcp.adapters import sw_type_info
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import bitmap
from solidworks_mcp.adapters.solidworks.edge_rules import EdgeRuleSelector
from solidworks_mcp.adapters.solidworks.features import _null_callout

OUT = Path(__file__).resolve().parents[1] / ".generated" / "probe_section_fillet"


async def _tools(adapter: PyWin32Adapter) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.export import register_export_tools
    from solidworks_mcp.tools.file_management import register_file_management_tools
    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("probe-section-fillet")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    await register_file_management_tools(mcp, adapter, {})
    await register_export_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


def _dispatch_array(items: list[Any]) -> Any:
    import pythoncom
    import win32com.client

    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, items)


def _difference(a: Path, b: Path) -> float | None:
    """The share of sampled pixels that differ between two BMPs."""
    if not (a.exists() and b.exists()):
        return None
    _wa, _ha, rows_a = bitmap.read_bmp(a)
    _wb, _hb, rows_b = bitmap.read_bmp(b)
    if len(rows_a) != len(rows_b):
        return 1.0
    total = changed = 0
    for row_a, row_b in zip(rows_a[::8], rows_b[::8], strict=True):
        for i in range(0, min(len(row_a), len(row_b)), 24):
            total += 1
            changed += row_a[i : i + 3] != row_b[i : i + 3]
    return round(changed / total, 4) if total else None


async def _volume(adapter: PyWin32Adapter) -> float | None:
    summary = await adapter.get_model_geometry_summary()
    return float(summary.data["volume_mm3"]) if summary.is_success else None


async def _block(tools: dict[str, Any]) -> str:
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    rect = {"x1": -20, "y1": -15, "x2": 20, "y2": 15}
    assert (await tools["add_rectangle"](rect))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    boss = await tools["create_extrusion"]({"depth": 10})
    assert boss["status"] == "success", boss
    return str(boss["extrusion"]["name"])


async def _section(adapter: PyWin32Adapter, tools: dict[str, Any], out: Path) -> dict:
    assert (await adapter.create_part()).is_success
    await _block(tools)
    hole = await tools["create_sketch"]({"plane": "Top"})
    assert hole["status"] == "success"
    assert (await tools["add_circle"]({"center_x": 0, "center_y": 0, "radius": 5}))[
        "status"
    ] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    assert (await tools["create_cut_extrude"]({"depth": 6}))["status"] == "success"
    pictures = {n: out / f"section_{n}.bmp" for n in ("before", "cut", "after")}
    shot = {"view_orientation": "isometric", "width": 800, "height": 600}
    report: dict[str, Any] = {}
    report["before"] = await tools["export_image"](
        {**shot, "file_path": str(pictures["before"])}
    )

    model = adapter.currentModel
    manager = model.ModelViewManager
    sw_type_info.flag_members(manager, "CreateSectionViewData", "RemoveSectionView")
    data = manager.CreateSectionViewData()
    plane = model.FeatureByName("Front Plane")
    sw_type_info.flag_members(plane, "GetSpecificFeature2")
    data.FirstPlane = plane.GetSpecificFeature2()
    data.FirstOffset = 0.0
    data.ShowSectionCap = True
    report["create"] = repr(manager.CreateSectionView(data))
    report["cut"] = await tools["export_image"](
        {**shot, "file_path": str(pictures["cut"])}
    )
    try:
        report["remove"] = repr(manager.RemoveSectionView())
    except Exception as exc:  # noqa: BLE001 - a probe records every failure
        report["remove"] = f"error: {exc}"
    report["after"] = await tools["export_image"](
        {**shot, "file_path": str(pictures["after"])}
    )
    report["changed_before_vs_cut"] = _difference(pictures["before"], pictures["cut"])
    report["changed_before_vs_after"] = _difference(
        pictures["before"], pictures["after"]
    )
    return report


async def _replace(
    adapter: PyWin32Adapter, feature_name: str, edges: list[Any]
) -> dict[str, Any]:
    model = adapter.currentModel
    feature = model.FeatureByName(feature_name)
    sw_type_info.flag_members(
        feature, "GetDefinition", "ModifyDefinition", "GetTypeName2"
    )
    kind = str(feature.GetTypeName2())
    data = feature.GetDefinition()
    sw_type_info.flag_members(
        data, "AccessSelections", "ReleaseSelectionAccess", "GetEdgeCount"
    )
    before = adapter._attempt(lambda: data.GetEdgeCount())
    if before is None:
        before = adapter._attempt(lambda: len(data.Edges or []))
    accessed = data.AccessSelections(model, _null_callout())
    report: dict[str, Any] = {
        "type": kind,
        "edges_before": before,
        "accessed": accessed,
    }
    try:
        data.Edges = _dispatch_array(edges)
        report["put"] = "ok"
    except Exception as exc:  # noqa: BLE001
        report["put"] = f"error: {exc}"
    report["modified"] = feature.ModifyDefinition(data, model, _null_callout())
    if not report["modified"]:
        adapter._attempt(lambda: data.ReleaseSelectionAccess())
    model.EditRebuild3()
    after = model.FeatureByName(feature_name)
    sw_type_info.flag_members(after, "GetDefinition", "GetErrorCode2")
    data_after = after.GetDefinition()
    sw_type_info.flag_members(data_after, "GetEdgeCount")
    report["edges_after"] = adapter._attempt(lambda: data_after.GetEdgeCount())
    if report["edges_after"] is None:
        report["edges_after"] = adapter._attempt(lambda: len(data_after.Edges or []))
    report["error_code"] = adapter._attempt(lambda: after.GetErrorCode2(None))
    return report


def _top_edges(adapter: PyWin32Adapter) -> list[Any]:
    selector = EdgeRuleSelector(adapter)
    return [edge for edge, _info in selector.candidates({"side": "+y"})]


async def _edges(adapter: PyWin32Adapter, tools: dict[str, Any], what: str) -> dict:
    assert (await adapter.create_part()).is_success
    await _block(tools)
    picked = await tools["select_edges"](
        {"side": "+y", "inside_box": [[-21, 9, 14], [21, 11, 16]]}
    )
    assert picked["status"] == "success", picked
    if what == "fillet":
        made = await tools["add_fillet"]({"radius": 1.0, "edge_names": []})
        name = made["fillet"]["name"]
    else:
        made = await tools["add_chamfer"]({"distance": 1.0, "edge_names": []})
        name = made.get("chamfer", {}).get("name") or made.get("data", {}).get("name")
    report = {"made": made.get("status"), "volume_before": await _volume(adapter)}
    report.update(await _replace(adapter, str(name), _top_edges(adapter)))
    report["volume_after"] = await _volume(adapter)
    return report


async def _broken(adapter: PyWin32Adapter, tools: dict[str, Any]) -> dict:
    assert (await adapter.create_part()).is_success
    sketch = await tools["create_sketch"]({"plane": "Top"})
    name = str(sketch["sketch"]["name"])
    corners = [(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30), (0, 0)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:], strict=False):
        line = {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
        assert (await tools["add_line"](line))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    assert (await tools["create_extrusion"]({"depth": 10}))["status"] == "success"
    # The inner corner's upright edge, at sketch (10, 10): model (10, y, -10).
    picked = await tools["select_edges"](
        {"parallel_to": "y", "inside_box": [[9, -1, -11], [11, 11, -9]]}
    )
    assert picked["status"] == "success", picked
    fillet = await tools["add_fillet"]({"radius": 2.0, "edge_names": []})
    fillet_name = str(fillet["fillet"]["name"])
    report: dict[str, Any] = {"fillet": fillet.get("status")}
    assert (await tools["edit_sketch"]({"name": name}))["status"] == "success"
    assert (await tools["delete_sketch_entities"]({"all": True}))["status"] == "success"
    rect = {"x1": 0, "y1": 0, "x2": 30, "y2": 30}
    assert (await tools["add_rectangle"](rect))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    report["rebuild_after_edit"] = await tools["rebuild_model"]({})
    selector = EdgeRuleSelector(adapter)
    upright = [
        edge
        for edge, info in selector.candidates({})
        if info.get("start_mm")
        and info.get("end_mm")
        and abs(info["start_mm"][0] - 30) < 1e-6
        and abs(info["end_mm"][0] - 30) < 1e-6
        and abs(info["start_mm"][2] - info["end_mm"][2]) < 1e-6
        and abs(info["start_mm"][1] - info["end_mm"][1]) > 1
    ][:1]
    report["replacement_edges"] = len(upright)
    report.update(await _replace(adapter, fillet_name, upright))
    report["rebuild_after_replace"] = await tools["rebuild_model"]({})
    return report


async def run() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT / stamp
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"started": stamp}
    adapter = PyWin32Adapter({})
    await adapter.connect()
    before = {
        str(adapter._get_attr_or_call(d, "GetTitle"))
        for d in adapter.swApp.GetDocuments() or []
    }
    try:
        tools = await _tools(adapter)
        for key, step in (
            ("section", lambda: _section(adapter, tools, out)),
            ("fillet_edges", lambda: _edges(adapter, tools, "fillet")),
            ("chamfer_edges", lambda: _edges(adapter, tools, "chamfer")),
            ("broken_fillet", lambda: _broken(adapter, tools)),
        ):
            try:
                report[key] = await step()
            except Exception as exc:  # noqa: BLE001 - keep probing the rest
                report[key] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"[probe] {key}: {json.dumps(report[key], default=str)[:600]}")
    finally:
        for title in {
            str(adapter._get_attr_or_call(d, "GetTitle"))
            for d in adapter.swApp.GetDocuments() or []
        } - before:
            adapter._attempt(lambda t=title: adapter.swApp.CloseDoc(t))
        await adapter.disconnect()
        path = out / "report.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"[probe] report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
