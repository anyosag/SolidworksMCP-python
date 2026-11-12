"""Edit an existing model in place: feature parameters, the rollback bar, sketches.

Deleting a feature to rebuild it takes its dependents with it (the Cellvis
dish rack lost two fillets that way). These change it where it stands:

* :func:`edit_feature`: an extrude's or cut's depth, end condition and
  direction, a revolve's angle, a fillet's radius, through the feature's
  definition (``IFeature.GetDefinition``, ``AccessSelections``, the
  ``Set*`` calls, ``IFeature.ModifyDefinition``). The values are read back
  after the rebuild, so the reply says what SolidWorks now holds.
* :func:`set_rollback`: ``IFeatureManager.EditRollback`` moves the rollback
  bar before or after a feature, or back to the end; new features go in at
  the bar.
* :func:`open_sketch` / :func:`delete_sketch_entities`: open an existing
  sketch for editing (``IModelDoc2.EditSketch``) with an id for each of its
  segments, so the ``add_*`` tools draw into it and its segments can be
  deleted by id.

Enum values are from SolidWorks 2026's ``swconst.tlb``.
"""

from __future__ import annotations

import math
from typing import Any

from .com_utils import as_list
from .com_utils import attempt as _attempt
from .com_utils import flag as _flag

#: ``swEndConditions_e`` by the name the tool takes (lower case, no spaces).
END_CONDITIONS: dict[str, tuple[str, int]] = {
    "blind": ("Blind", 0),
    "throughall": ("ThroughAll", 1),
    "midplane": ("MidPlane", 6),
    "throughallboth": ("ThroughAllBoth", 9),
    "uptonext": ("UpToNext", 11),
}
_END_CONDITION_NAMES = {value: name for name, value in END_CONDITIONS.values()}

#: ``swMoveRollbackBarTo_e``.
ROLLBACK_TO_END = 1
ROLLBACK_BEFORE = 3
ROLLBACK_AFTER = 4

#: ``GetTypeName2`` of an extrude made with Instant3D, boss and cut alike
#: (live, SolidWorks 2026: Boss-Extrudes and Cut-Extrudes). The API help
#: says ``IFeature.GetTypeName`` gives such a feature's underlying type.
INSTANT3D = "ICE"

_EXTRUDE_EDITS = frozenset({"depth", "end_condition", "reverse_direction"})

#: ``IFeature.GetTypeName2`` -> which parameters ``edit_feature`` changes.
#: "ICE" stays only when ``GetTypeName`` gives no extrude type; boss and
#: cut take the same changes.
EDITABLE: dict[str, frozenset[str]] = {
    "Extrusion": _EXTRUDE_EDITS,
    "Cut": _EXTRUDE_EDITS,
    INSTANT3D: _EXTRUDE_EDITS,
    "Revolution": frozenset({"angle", "reverse_direction"}),
    "RevCut": frozenset({"angle", "reverse_direction"}),
    "Fillet": frozenset({"radius"}),
}

_EXTRUDE_KINDS = ("Extrusion", "Cut", INSTANT3D)

#: ``GetTypeName`` names of an Instant3D extrude's underlying type, lower
#: case; it may not use ``GetTypeName2``'s capitals ("CUT" was reported).
_UNDERLYING = {"extrusion": "Extrusion", "boss": "Extrusion", "cut": "Cut"}


def feature_kind(adapter: Any, feature: Any) -> str:
    """A feature's ``GetTypeName2``, or for an Instant3D extrude its real type.

    Returns:
        str: ``"Extrusion"`` or ``"Cut"`` for an "ICE" feature whose
        ``GetTypeName`` names one, else ``GetTypeName2`` as given.
    """
    kind = str(_attempt(adapter, lambda: feature.GetTypeName2()) or "")
    if kind != INSTANT3D:
        return kind
    older = str(_attempt(adapter, lambda: feature.GetTypeName()) or "")
    return _UNDERLYING.get(older.lower(), kind)


#: ``swSketchSegments_e`` -> the id prefix a segment gets.
SEGMENT_PREFIXES = {
    0: "Line",
    1: "Arc",
    2: "Ellipse",
    3: "Spline",
    4: "Text",
    5: "Parabola",
}

_DATA_MEMBERS = (
    "AccessSelections",
    "ReleaseSelectionAccess",
    "GetDepth",
    "SetDepth",
    "GetEndCondition",
    "SetEndCondition",
    "GetRevolutionAngle",
    "SetRevolutionAngle",
)


def end_condition_value(name: str) -> tuple[str, int]:
    """The SolidWorks name and value of an end condition.

    Raises:
        ValueError: For one ``edit_feature`` doesn't set.
    """
    key = "".join(c for c in name.lower() if c not in " _-")
    if key not in END_CONDITIONS:
        names = ", ".join(n for n, _ in END_CONDITIONS.values())
        raise ValueError(f"end_condition must be one of {names}, not {name!r}")
    return END_CONDITIONS[key]


def check_changes(kind: str, changes: dict[str, Any], name: str) -> str | None:
    """What is wrong with editing ``changes`` on a ``kind`` feature, or None."""
    if not changes:
        return "Give at least one change: depth, end_condition, reverse_direction, angle or radius."
    allowed = EDITABLE.get(kind)
    if allowed is None:
        return (
            f"{name!r} is a {kind or 'feature'}; edit_feature changes extrudes, "
            "cuts, revolves and fillets. Change other features' dimensions with "
            "set_dimension."
        )
    extra = sorted(set(changes) - allowed)
    if extra:
        return (
            f"{name!r} is a {kind}; it takes {', '.join(sorted(allowed))}, not "
            f"{', '.join(extra)}."
        )
    if "end_condition" in changes:
        try:
            end_condition_value(str(changes["end_condition"]))
        except ValueError as exc:
            return str(exc)
    return None


def _feature(adapter: Any, name: str) -> Any:
    model = adapter.currentModel
    feature = _attempt(adapter, lambda: model.FeatureByName(name))
    if feature is None:
        raise LookupError(f"Feature {name!r} not found; list_features names them.")
    _flag(
        adapter,
        feature,
        "GetTypeName2",
        "GetTypeName",
        "GetDefinition",
        "ModifyDefinition",
    )
    return feature


def _read(adapter: Any, kind: str, data: Any) -> dict[str, Any]:
    """The editable values a definition holds, in mm and degrees."""
    values: dict[str, Any] = {}
    if kind in _EXTRUDE_KINDS:
        depth = _attempt(adapter, lambda: data.GetDepth(True))
        end = _attempt(adapter, lambda: data.GetEndCondition(True))
        values["depth"] = None if depth is None else round(float(depth) * 1000, 6)
        values["end_condition"] = _END_CONDITION_NAMES.get(end, end)
    if kind in ("Revolution", "RevCut"):
        angle = _attempt(adapter, lambda: data.GetRevolutionAngle(True))
        values["angle"] = None if angle is None else round(math.degrees(angle), 6)
    if kind in (*_EXTRUDE_KINDS, "Revolution", "RevCut"):
        reverse = _attempt(adapter, lambda: data.ReverseDirection)
        values["reverse_direction"] = None if reverse is None else bool(reverse)
    if kind == "Fillet":
        radius = _attempt(adapter, lambda: data.DefaultRadius)
        values["radius"] = None if radius is None else round(float(radius) * 1000, 6)
    return values


def _write(data: Any, changes: dict[str, Any]) -> None:
    """Put ``changes`` into a definition whose selections are accessed."""
    if "end_condition" in changes:
        data.SetEndCondition(
            True, end_condition_value(str(changes["end_condition"]))[1]
        )
    if "depth" in changes:
        data.SetDepth(True, float(changes["depth"]) / 1000.0)
    if "angle" in changes:
        data.SetRevolutionAngle(True, math.radians(float(changes["angle"])))
    if "reverse_direction" in changes:
        data.ReverseDirection = bool(changes["reverse_direction"])
    if "radius" in changes:
        data.DefaultRadius = float(changes["radius"]) / 1000.0


def edit_feature(
    adapter: Any, name: str, changes: dict[str, Any], null_component: Any
) -> dict[str, Any]:
    """Change an existing feature's parameters and read them back.

    Args:
        adapter: A connected adapter with a ``currentModel``.
        name: The feature's tree name.
        changes: ``depth`` (mm), ``end_condition``, ``reverse_direction``,
            ``angle`` (degrees) or ``radius`` (mm).
        null_component: The null ``IComponent2`` the definition calls take
            for a part (a ``VT_DISPATCH`` null; ``None`` is a type mismatch).

    Returns:
        dict[str, Any]: ``feature``, ``type``, ``before`` and ``after``.

    Raises:
        LookupError: No such feature.
        ValueError: A change this kind of feature doesn't take.
        RuntimeError: SolidWorks gave no definition or refused the change.
    """
    model = adapter.currentModel
    feature = _feature(adapter, name)
    kind = feature_kind(adapter, feature)
    problem = check_changes(kind, changes, name)
    if problem:
        raise ValueError(problem)
    data = _attempt(adapter, lambda: feature.GetDefinition())
    if data is None:
        raise RuntimeError(
            f"SolidWorks gave no definition for {name!r}, so it can't be edited "
            "this way; change a dimension with set_dimension (e.g. "
            f"'D1@{name}') instead."
        )
    _flag(adapter, data, *_DATA_MEMBERS)
    before = _read(adapter, kind, data)
    if not _attempt(
        adapter, lambda: data.AccessSelections(model, null_component), False
    ):
        raise RuntimeError(
            f"SolidWorks would not open {name!r}'s definition for editing."
        )
    try:
        _write(data, changes)
    except Exception:
        _attempt(
            adapter, lambda: adapter._get_attr_or_call(data, "ReleaseSelectionAccess")
        )
        raise
    if not feature.ModifyDefinition(data, model, null_component):
        _attempt(
            adapter, lambda: adapter._get_attr_or_call(data, "ReleaseSelectionAccess")
        )
        raise RuntimeError(
            f"SolidWorks refused the change to {name!r} (ModifyDefinition "
            "returned False); the feature is as it was. rebuild_model says why "
            "a value can't apply."
        )
    _attempt(adapter, lambda: model.EditRebuild3())
    after_data = _attempt(adapter, lambda: _feature(adapter, name).GetDefinition())
    if after_data is not None:
        _flag(adapter, after_data, *_DATA_MEMBERS)
    after = (
        _read(adapter, kind, after_data) if after_data is not None else dict(changes)
    )
    return {"feature": name, "type": kind, "before": before, "after": after}


def rolled_back_features(adapter: Any) -> list[str]:
    """The names of the features below the rollback bar, in tree order."""
    model = adapter.currentModel
    _flag(adapter, model, "FirstFeature")
    names: list[str] = []
    feature = _attempt(adapter, lambda: model.FirstFeature())
    guard = 0
    while feature is not None and guard < 10000:
        guard += 1
        _flag(adapter, feature, "IsRolledBack", "GetNextFeature")
        if _attempt(adapter, lambda f=feature: f.IsRolledBack(), False):
            names.append(str(_attempt(adapter, lambda f=feature: f.Name, "")))
        feature = _attempt(adapter, lambda f=feature: f.GetNextFeature())
    return names


def set_rollback(adapter: Any, before: str | None, after: str | None) -> dict[str, Any]:
    """Move the rollback bar before or after a feature, or to the end.

    Args:
        adapter: A connected adapter with a ``currentModel``.
        before: Put the bar just above this feature.
        after: Put the bar just below this feature.

    Returns:
        dict[str, Any]: ``position`` in words and ``rolled_back``, the
        features now below the bar.

    Raises:
        LookupError: The named feature isn't in the tree.
        RuntimeError: SolidWorks didn't move the bar.
    """
    model = adapter.currentModel
    target = before or after
    if target:
        _feature(adapter, target)  # a clear not-found before EditRollback
    manager = model.FeatureManager
    _flag(adapter, manager, "EditRollback")
    location = (
        ROLLBACK_BEFORE if before else ROLLBACK_AFTER if after else ROLLBACK_TO_END
    )
    moved = manager.EditRollback(location, target or "")
    if not moved:
        raise RuntimeError(
            f"SolidWorks did not move the rollback bar "
            f"{'to the end' if not target else ('before ' if before else 'after ') + repr(target)}."
        )
    position = (
        f"before {target}" if before else f"after {target}" if after else "the end"
    )
    return {"position": position, "rolled_back": rolled_back_features(adapter)}


def _point_mm(adapter: Any, point: Any) -> list[float] | None:
    if point is None:
        return None
    coords = [_attempt(adapter, lambda a=axis: getattr(point, a)) for axis in "XY"]
    if any(c is None for c in coords):
        return None
    return [round(float(c) * 1000, 6) for c in coords]


def describe_segment(adapter: Any, segment: Any) -> dict[str, Any]:
    """A sketch segment's kind and points in sketch mm, as far as they read."""
    _flag(
        adapter, segment, "GetType", "GetStartPoint2", "GetEndPoint2", "GetCenterPoint2"
    )
    kind = _attempt(adapter, lambda: segment.GetType())
    info: dict[str, Any] = {"type": SEGMENT_PREFIXES.get(kind, "Segment").lower()}
    for key, getter in (
        ("start_mm", "GetStartPoint2"),
        ("end_mm", "GetEndPoint2"),
        ("center_mm", "GetCenterPoint2"),
    ):
        point = _point_mm(
            adapter, _attempt(adapter, lambda g=getter: getattr(segment, g)())
        )
        if point is not None:
            info[key] = point
    construction = _attempt(adapter, lambda: segment.ConstructionGeometry)
    if construction is not None:
        info["construction"] = bool(construction)
    return info


def open_sketch(adapter: Any, name: str) -> dict[str, Any]:
    """Open an existing sketch for editing and give each of its segments an id.

    Args:
        adapter: A connected ``PyWin32Adapter`` with a ``currentModel``.
        name: The sketch's tree name.

    Returns:
        dict[str, Any]: ``sketch`` and ``segments`` (each with ``id``,
        ``type`` and its points in sketch mm).

    Raises:
        LookupError: No such feature.
        ValueError: It isn't a sketch.
        RuntimeError: SolidWorks didn't open it.
    """
    from .visibility import SKETCH_TYPES

    model = adapter.currentModel
    feature = _feature(adapter, name)
    kind = str(_attempt(adapter, lambda: feature.GetTypeName2()) or "")
    if kind not in SKETCH_TYPES:
        raise ValueError(f"{name!r} is a {kind or 'feature'}, not a sketch.")
    _flag(adapter, feature, "Select2", "GetSpecificFeature2")
    _flag(adapter, model, "ClearSelection2", "EditSketch")
    _attempt(adapter, lambda: model.ClearSelection2(True))
    if not _attempt(adapter, lambda: feature.Select2(False, 0), False):
        raise RuntimeError(f"SolidWorks could not select sketch {name!r}.")
    # A void zero-argument method: runs once whether or not it was flagged.
    adapter._get_attr_or_call(model, "EditSketch")
    manager = model.SketchManager
    sketch = _attempt(adapter, lambda: manager.ActiveSketch)
    if sketch is None:
        raise RuntimeError(f"SolidWorks did not open sketch {name!r} for editing.")
    adapter.currentSketchManager = manager
    adapter.currentSketch = sketch
    adapter._last_sketch_name = name
    adapter._reset_sketch_entity_registry()
    manager.AddToDB = True  # as create_sketch: points land where asked
    _flag(adapter, sketch, "GetSketchSegments")
    segments = []
    for segment in as_list(_attempt(adapter, lambda: sketch.GetSketchSegments())):
        info = describe_segment(adapter, segment)
        entity_id = adapter._register_sketch_entity(info["type"].capitalize(), segment)
        segments.append({"id": entity_id, **info})
    return {"sketch": name, "segments": segments}


def delete_sketch_entities(adapter: Any, entity_ids: list[str]) -> dict[str, Any]:
    """Delete entities of the open sketch by id.

    Raises:
        LookupError: An id isn't in the open sketch.
        RuntimeError: SolidWorks didn't select or delete them.
    """
    missing = [i for i in entity_ids if i not in adapter._sketch_entities]
    if missing:
        raise LookupError(
            f"Sketch entity {', '.join(missing)} not found in the open sketch."
        )
    model = adapter.currentModel
    _flag(adapter, model, "ClearSelection2", "EditDelete")
    _attempt(adapter, lambda: model.ClearSelection2(True))
    for index, entity_id in enumerate(entity_ids):
        if not adapter._select_sketch_entity(
            adapter._sketch_entities[entity_id], index > 0
        ):
            _attempt(adapter, lambda: model.ClearSelection2(True))
            raise RuntimeError(f"SolidWorks could not select {entity_id}.")
    adapter._get_attr_or_call(model, "EditDelete")
    for entity_id in entity_ids:
        adapter._sketch_entities.pop(entity_id, None)
        adapter._sketch_entity_centers.pop(entity_id, None)
    return {"deleted": list(entity_ids), "remaining": sorted(adapter._sketch_entities)}
