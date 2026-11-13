"""Probe the distance calls for ``measure_clearance``, and the rotation rows.

Tasks 1.1 and 1.3 of the ``cellvis-assembly-and-print-checks`` OpenSpec
change. It builds scratch parts and an assembly through ``PyWin32Adapter``:

* a 60 x 40 x 10 plate with a Ø10 hole and a 4.5 mm wide slot, and a Ø9.5 pin
  and a 4.0 mm wide tongue placed in them: both clearances are 0.25 mm;
* a 20 x 10 x 6 block turned a quarter turn about Y.

Then it records:

* for every face pair of the pin and the plate, and of the tongue and the
  plate: ``IModelDoc2.ClosestDistance`` and ``IEntity.GetDistance`` (min), on
  the faces in assembly context (``IComponent2.GetCorrespondingEntity``);
* ``IMeasure.Calculate`` with the two components selected;
* each face's box from the part (``IFace2.GetBox``) and in assembly context,
  to see which coordinates ``GetBox`` gives;
* the turned block's ``Transform2.ArrayData`` and its faces' assembly boxes,
  to see where a quarter turn about Y puts the block's +X.

It only touches documents it creates and deletes its files at the end. The
report stays in ``tests/.generated/probe_clearance/``.

Usage (SolidWorks running, nothing else driving it, the user's OK)::

    .venv\\Scripts\\python.exe tests/scripts/probe_clearance.py
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
from solidworks_mcp.adapters.solidworks import placement
from solidworks_mcp.adapters.solidworks.io import (
    _as_com,
    _byref_double,
    _byref_variant,
    _component_pairs,
)

OUT = Path(__file__).resolve().parents[1] / ".generated" / "probe_clearance"


async def _tools(adapter: PyWin32Adapter) -> dict[str, Any]:
    from fastmcp import FastMCP

    from solidworks_mcp.tools.modeling import register_modeling_tools
    from solidworks_mcp.tools.sketching import register_sketching_tools

    mcp = FastMCP("probe-clearance")
    await register_sketching_tools(mcp, adapter, {})
    await register_modeling_tools(mcp, adapter, {})
    return {t.name: t.fn for t in await mcp.list_tools()}


async def _extrude(tools: dict[str, Any], shape: dict[str, Any], depth: float) -> None:
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    kind = shape.pop("kind")
    assert (await tools[kind](shape))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    made = await tools["create_extrusion"]({"depth": depth})
    assert made["status"] == "success", made


async def _cut(tools: dict[str, Any], shape: dict[str, Any]) -> None:
    assert (await tools["create_sketch"]({"plane": "Top"}))["status"] == "success"
    kind = shape.pop("kind")
    assert (await tools[kind](shape))["status"] == "success"
    assert (await tools["exit_sketch"]())["status"] == "success"
    cut = await tools["create_cut_extrude"](
        {"depth": 10, "end_condition": "ThroughAllBoth"}
    )
    assert cut["status"] == "success", cut


async def _part(adapter: PyWin32Adapter, path: Path, build: Any) -> str:
    assert (await adapter.create_part()).is_success
    await build()
    saved = await adapter.save_file(str(path))
    assert saved.is_success, saved.error
    return str(path)


def _faces(adapter: PyWin32Adapter, component: Any) -> list[dict[str, Any]]:
    """Each face of a component: the part face, its box, and its assembly twin."""
    sw_type_info.flag_members(component, "GetBodies2", "GetCorrespondingEntity")
    out = []
    for body in component.GetBodies2(0) or []:
        sw_type_info.flag_members(body, "GetFaces")
        for face in body.GetFaces() or []:
            sw_type_info.flag_members(face, "GetBox", "GetSurface")
            twin = adapter._attempt(lambda f=face: component.GetCorrespondingEntity(f))
            if twin is not None:
                sw_type_info.flag_members(twin, "GetBox", "GetDistance")
            surface = adapter._attempt(lambda f=face: f.GetSurface())
            if surface is not None:
                sw_type_info.flag_members(surface, "IsCylinder", "IsPlane")
            out.append(
                {
                    "face": face,
                    "twin": twin,
                    "kind": (
                        "cylinder"
                        if adapter._attempt(lambda s=surface: s.IsCylinder(), False)
                        else "plane"
                        if adapter._attempt(lambda s=surface: s.IsPlane(), False)
                        else "other"
                    ),
                    "box_part_mm": [round(v * 1000, 4) for v in face.GetBox()],
                    "box_twin_mm": (
                        [round(v * 1000, 4) for v in twin.GetBox()] if twin else None
                    ),
                }
            )
    return out


def _closest(model: Any, a: Any, b: Any) -> dict[str, Any]:
    p1, p2 = _byref_variant(), _byref_variant()
    try:
        d = model.ClosestDistance(a, b, p1, p2)
    except Exception as exc:  # noqa: BLE001 - a probe records every failure
        return {"error": str(exc)}
    return {
        "mm": None if d is None else round(float(d) * 1000, 6),
        "p1": getattr(p1, "value", None),
        "p2": getattr(p2, "value", None),
    }


def _entity(a: Any, b: Any) -> dict[str, Any]:
    p1, p2, d = _byref_variant(), _byref_variant(), _byref_double()
    try:
        status = a.GetDistance(b, True, None, p1, p2, d)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    value = getattr(d, "value", None)
    return {
        "status": status,
        "mm": None if value is None else round(float(value) * 1000, 6),
        "p1": getattr(p1, "value", None),
        "p2": getattr(p2, "value", None),
    }


def _measure(adapter: PyWin32Adapter, model: Any, a: Any, b: Any) -> dict[str, Any]:
    ext = model.Extension
    sw_type_info.flag_members(ext, "CreateMeasure")
    measure = ext.CreateMeasure()
    sw_type_info.flag_members(measure, "Calculate")
    sel = sw_type_info.flagged(model.SelectionManager, "ISelectionMgr")
    model.ClearSelection2(True)
    data = sel.CreateSelectData()
    a.Select4(False, data, False)
    b.Select4(True, data, False)
    try:
        ok = measure.Calculate(None)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    finally:
        model.ClearSelection2(True)
    return {"ok": ok, "distance_mm": round(float(measure.Distance) * 1000, 6)}


def _pairs(adapter: PyWin32Adapter, model: Any, a: Any, b: Any) -> dict[str, Any]:
    faces_a, faces_b = _faces(adapter, a), _faces(adapter, b)
    rows = []
    for fa in faces_a:
        for fb in faces_b:
            if fa["twin"] is None or fb["twin"] is None:
                continue
            rows.append(
                {
                    "kinds": [fa["kind"], fb["kind"]],
                    "boxes_a": [fa["box_part_mm"], fa["box_twin_mm"]],
                    "boxes_b": [fb["box_part_mm"], fb["box_twin_mm"]],
                    "closest": _closest(model, fa["twin"], fb["twin"]),
                    "entity": _entity(fa["twin"], fb["twin"]),
                }
            )

    def best(key: str) -> Any:
        values = [r[key]["mm"] for r in rows if isinstance(r[key].get("mm"), float)]
        return min(values) if values else None

    return {
        "pairs": len(rows),
        "min_closest_mm": best("closest"),
        "min_entity_mm": best("entity"),
        "measure": _measure(adapter, model, a, b),
        "rows": rows,
    }


async def run() -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT / stamp
    scratch = out / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"started": stamp}
    adapter = PyWin32Adapter({})
    await adapter.connect()
    before = {
        str(adapter._get_attr_or_call(d, "GetTitle"))
        for d in adapter.swApp.GetDocuments() or []
    }
    try:
        tools = await _tools(adapter)

        async def plate() -> None:
            await _extrude(
                tools,
                {"kind": "add_rectangle", "x1": -30, "y1": -20, "x2": 30, "y2": 20},
                10,
            )
            await _cut(
                tools,
                {"kind": "add_circle", "center_x": 15, "center_y": 0, "radius": 5},
            )
            await _cut(
                tools,
                {"kind": "add_rectangle", "x1": -20, "y1": -2.25, "x2": -5, "y2": 2.25},
            )

        async def pin() -> None:
            await _extrude(
                tools,
                {"kind": "add_circle", "center_x": 0, "center_y": 0, "radius": 4.75},
                30,
            )

        async def tongue() -> None:
            await _extrude(
                tools,
                {"kind": "add_rectangle", "x1": -5, "y1": -2, "x2": 5, "y2": 2},
                30,
            )

        async def block() -> None:
            await _extrude(
                tools,
                {"kind": "add_rectangle", "x1": 0, "y1": 0, "x2": 20, "y2": 10},
                6,
            )

        paths = {
            name: await _part(adapter, scratch / f"pc_{name}.SLDPRT", build)
            for name, build in (
                ("plate", plate),
                ("pin", pin),
                ("tongue", tongue),
                ("block", block),
            )
        }
        assert (await adapter.create_assembly()).is_success
        # The sketches' (x, y) on Top are model (x, -z): the hole is at x 15,
        # the slot centred at x -12.5; both run along Y through the plate.
        for name, origin in (
            ("plate", (0, 0, 0)),
            ("pin", (15, -10, 0)),
            ("tongue", (-12.5, -10, 0)),
            ("block", (100, 0, 0)),
        ):
            placed = await adapter.insert_component(paths[name], *origin)
            report[f"insert_{name}"] = (
                placed.data if placed.is_success else placed.error
            )
        model = adapter.currentModel
        assembly = sw_type_info.flagged(model, "IAssemblyDoc")
        components = {
            name.split("_")[1].split("-")[0]: _as_com(adapter, comp, "IComponent2")
            for name, comp in _component_pairs(adapter, assembly)
        }
        report["components"] = sorted(components)

        report["pin_in_hole"] = _pairs(
            adapter, model, components["pin"], components["plate"]
        )
        report["tongue_in_slot"] = _pairs(
            adapter, model, components["tongue"], components["plate"]
        )

        quarter_y = placement.rotation_rows_from_deg(0, 90, 0)
        turned = placement.place(
            adapter, model, assembly, components["block"], (0.1, 0.0, 0.0), quarter_y
        )
        block_component = components["block"]
        sw_type_info.flag_members(block_component, "GetBox")
        component_box = adapter._attempt(lambda: block_component.GetBox(False, False))
        report["quarter_turn_about_y"] = {
            "asked_rows": quarter_y,
            "place": turned,
            "component_box_mm": (
                [round(float(v) * 1000, 3) for v in component_box]
                if component_box
                else None
            ),
            "face_boxes_mm": [
                f["box_twin_mm"] for f in _faces(adapter, components["block"])
            ],
            # The block is x 0..20, y 0..6 (extruded along +Y), z -10..0 in
            # its part. With rows as axes (p . R + t), X goes to -z, Y stays,
            # Z goes to +x: x 90..100, y 0..6, z -20..0 mm in the assembly.
            "expected_box_if_rows_are_axes_mm": [90, 0, -20, 100, 6, 0],
        }
    finally:
        for title in {
            str(adapter._get_attr_or_call(d, "GetTitle"))
            for d in adapter.swApp.GetDocuments() or []
        } - before:
            adapter._attempt(lambda t=title: adapter.swApp.CloseDoc(t))
        await adapter.disconnect()
        for path in scratch.glob("*"):
            try:
                path.unlink()
            except OSError:
                pass
        for row_set in ("pin_in_hole", "tongue_in_slot"):
            if row_set in report:
                for row in report[row_set]["rows"]:
                    for key in ("closest", "entity"):
                        for p in ("p1", "p2"):
                            if row[key].get(p) is not None:
                                row[key][p] = [
                                    round(float(v) * 1000, 4) for v in row[key][p]
                                ]
        path = out / "report.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"[probe] report: {path}")
        for key in ("pin_in_hole", "tongue_in_slot"):
            if key in report:
                r = report[key]
                print(
                    f"[probe] {key}: pairs {r['pairs']}, ClosestDistance min "
                    f"{r['min_closest_mm']} mm, IEntity.GetDistance min "
                    f"{r['min_entity_mm']} mm, IMeasure {r['measure']}"
                )
        if "quarter_turn_about_y" in report:
            print(f"[probe] quarter turn: {report['quarter_turn_about_y']['place']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
