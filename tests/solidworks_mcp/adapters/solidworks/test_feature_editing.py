"""Editing an existing model in place (``feature_editing``)."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import feature_editing as fe

_NULL = object()  # stands in for the VT_DISPATCH null component


class _ExtrudeData:
    """``IExtrudeFeatureData2``: 10 mm blind, one way."""

    def __init__(self, access: bool = True, refuse_set: bool = False) -> None:
        self.depth, self.end, self.ReverseDirection = 0.01, 0, False
        self._access, self._refuse = access, refuse_set
        self.accessed_with: tuple[Any, ...] = ()
        self.released = 0

    def AccessSelections(self, doc: Any, component: Any) -> bool:  # noqa: N802
        self.accessed_with = (doc, component)
        return self._access

    def ReleaseSelectionAccess(self) -> None:  # noqa: N802
        self.released += 1

    def GetDepth(self, forward: bool) -> float:  # noqa: N802
        return self.depth

    def SetDepth(self, forward: bool, depth: float) -> None:  # noqa: N802
        if self._refuse:
            raise RuntimeError("type mismatch")
        self.depth = depth

    def GetEndCondition(self, forward: bool) -> int:  # noqa: N802
        return self.end

    def SetEndCondition(self, forward: bool, value: int) -> None:  # noqa: N802
        self.end = value


class _RevolveData:
    def __init__(self) -> None:
        self.angle, self.ReverseDirection = math.pi, False

    def AccessSelections(self, *_a: Any) -> bool:  # noqa: N802
        return True

    def GetRevolutionAngle(self, forward: bool) -> float:  # noqa: N802
        return self.angle

    def SetRevolutionAngle(self, forward: bool, angle: float) -> None:  # noqa: N802
        self.angle = angle


class _Feature:
    def __init__(self, name: str, kind: str, data: Any, modify: bool = True) -> None:
        self.Name, self._kind, self._data, self._modify = name, kind, data, modify
        self.rolled_back = False
        self.after: _Feature | None = None

    def GetTypeName2(self) -> str:  # noqa: N802
        return self._kind

    def GetDefinition(self) -> Any:  # noqa: N802
        return self._data

    def ModifyDefinition(self, data: Any, doc: Any, component: Any) -> bool:  # noqa: N802
        return self._modify

    def Select2(self, *_a: Any) -> bool:  # noqa: N802
        return True

    def IsRolledBack(self) -> bool:  # noqa: N802
        return self.rolled_back

    def GetNextFeature(self) -> _Feature | None:  # noqa: N802
        return self.after


class _Manager:
    def __init__(self, model: _Model, moves: bool = True) -> None:
        self._model, self._moves = model, moves
        self.calls: list[tuple[int, str]] = []

    def EditRollback(self, location: int, name: str) -> bool:  # noqa: N802
        self.calls.append((location, name))
        if not self._moves:
            return False
        names = [f.Name for f in self._model.tree]
        cut = {
            fe.ROLLBACK_BEFORE: names.index(name) if name in names else 0,
            fe.ROLLBACK_AFTER: names.index(name) + 1 if name in names else 0,
            fe.ROLLBACK_TO_END: len(names),
        }[location]
        for index, feature in enumerate(self._model.tree):
            feature.rolled_back = index >= cut
        return True


class _Point:
    def __init__(self, x_mm: float, y_mm: float) -> None:
        self.X, self.Y = x_mm / 1000, y_mm / 1000


class _Segment:
    def __init__(
        self, kind: int, start: Any = None, end: Any = None, center: Any = None
    ) -> None:
        self._kind, self._start, self._end, self._center = kind, start, end, center
        self.ConstructionGeometry = False
        self.selectable = True

    def GetType(self) -> int:  # noqa: N802
        return self._kind

    def GetStartPoint2(self) -> Any:  # noqa: N802
        return self._start

    def GetEndPoint2(self) -> Any:  # noqa: N802
        return self._end

    def GetCenterPoint2(self) -> Any:  # noqa: N802
        if self._center is None:
            raise AttributeError("not an arc")
        return self._center


class _Model:
    def __init__(
        self, tree: list[_Feature], sketch: Any = None, moves: bool = True
    ) -> None:
        self.tree = tree
        for first, second in zip(tree, tree[1:], strict=False):
            first.after = second
        self.FeatureManager = _Manager(self, moves)
        self.SketchManager = SimpleNamespace(ActiveSketch=sketch)
        self.calls: list[str] = []

    def FeatureByName(self, name: str) -> Any:  # noqa: N802
        return next((f for f in self.tree if f.Name == name), None)

    def FirstFeature(self) -> Any:  # noqa: N802
        return self.tree[0] if self.tree else None

    def EditRebuild3(self) -> bool:  # noqa: N802
        self.calls.append("rebuild")
        return True

    def ClearSelection2(self, _all: bool) -> None:  # noqa: N802
        self.calls.append("clear")

    def EditSketch(self) -> None:  # noqa: N802
        self.calls.append("EditSketch")

    def EditDelete(self) -> None:  # noqa: N802
        self.calls.append("EditDelete")


class _Adapter:
    def __init__(self, model: _Model) -> None:
        self.currentModel = model
        self.currentSketchManager: Any = None
        self.currentSketch: Any = None
        self._last_sketch_name: str | None = None
        self._sketch_entities: dict[str, Any] = {}
        self._sketch_entity_centers: dict[str, Any] = {}
        self._next = 1

    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001
            return default

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value

    def _reset_sketch_entity_registry(self) -> None:
        self._sketch_entities.clear()

    def _register_sketch_entity(self, prefix: str, entity: Any) -> str:
        entity_id = f"{prefix}_{self._next}"
        self._next += 1
        self._sketch_entities[entity_id] = entity
        return entity_id

    def _select_sketch_entity(self, entity: Any, _append: bool) -> bool:
        return bool(entity.selectable)


# ---- change rules -------------------------------------------------------------


def test_end_conditions_by_any_spelling() -> None:
    assert fe.end_condition_value("Through All") == ("ThroughAll", 1)
    assert fe.end_condition_value("mid_plane") == ("MidPlane", 6)
    with pytest.raises(ValueError, match="end_condition must be one of"):
        fe.end_condition_value("UpToVertex")


@pytest.mark.parametrize(
    ("kind", "changes", "fragment"),
    [
        ("Cut", {}, "Give at least one change"),
        ("Chamfer", {"depth": 1}, "edit_feature changes extrudes, cuts"),
        ("Fillet", {"depth": 1}, "it takes radius, not depth"),
        ("Cut", {"end_condition": "sideways"}, "end_condition must be one of"),
    ],
)
def test_changes_a_feature_does_not_take(
    kind: str, changes: dict[str, Any], fragment: str
) -> None:
    assert fragment in (fe.check_changes(kind, changes, "F1") or "")


def test_a_cut_takes_depth_end_condition_and_direction() -> None:
    assert fe.check_changes("Cut", {"depth": 3, "end_condition": "Blind"}, "C") is None


# ---- edit_feature ------------------------------------------------------------


@pytest.mark.parametrize("type_name", ["Cut", "ICE"])
def test_a_cuts_depth_and_direction_change_and_read_back(type_name: str) -> None:
    """SolidWorks 2026 names a cut-extrude's type "ICE" (first live run)."""
    data = _ExtrudeData()
    model = _Model([_Feature("Cut-Extrude1", type_name, data)])

    reply = fe.edit_feature(
        _Adapter(model),
        "Cut-Extrude1",
        {"depth": 4.5, "end_condition": "ThroughAll", "reverse_direction": True},
        _NULL,
    )

    assert reply["before"] == {
        "depth": 10.0,
        "end_condition": "Blind",
        "reverse_direction": False,
    }
    assert reply["after"] == {
        "depth": 4.5,
        "end_condition": "ThroughAll",
        "reverse_direction": True,
    }
    assert data.accessed_with == (model, _NULL)
    assert model.calls == ["rebuild"]


def test_a_revolve_angle_in_degrees() -> None:
    model = _Model([_Feature("Revolve1", "Revolution", _RevolveData())])

    reply = fe.edit_feature(_Adapter(model), "Revolve1", {"angle": 90}, _NULL)

    assert (reply["before"]["angle"], reply["after"]["angle"]) == (180.0, 90.0)


def test_a_fillet_radius() -> None:
    data = SimpleNamespace(DefaultRadius=0.002, AccessSelections=lambda *_a: True)
    model = _Model([_Feature("Fillet1", "Fillet", data)])

    reply = fe.edit_feature(_Adapter(model), "Fillet1", {"radius": 1.5}, _NULL)

    assert (reply["before"]["radius"], reply["after"]["radius"]) == (2.0, 1.5)


@pytest.mark.parametrize(
    ("feature", "error", "fragment"),
    [
        (None, LookupError, "'Cut-Extrude1' not found"),
        (_Feature("Cut-Extrude1", "Cut", None), RuntimeError, "gave no definition"),
        (
            _Feature("Cut-Extrude1", "Cut", _ExtrudeData(access=False)),
            RuntimeError,
            "would not open",
        ),
        (
            _Feature("Cut-Extrude1", "Cut", _ExtrudeData(), modify=False),
            RuntimeError,
            "refused the change",
        ),
        (
            _Feature("Cut-Extrude1", "Chamfer", _ExtrudeData()),
            ValueError,
            "edit_feature",
        ),
    ],
)
def test_edits_that_fail_say_why(
    feature: Any, error: type[Exception], fragment: str
) -> None:
    model = _Model([feature] if feature else [])

    with pytest.raises(error, match=None) as caught:
        fe.edit_feature(_Adapter(model), "Cut-Extrude1", {"depth": 2}, _NULL)
    assert fragment in str(caught.value)


def test_a_set_that_raises_releases_the_definition() -> None:
    data = _ExtrudeData(refuse_set=True)
    model = _Model([_Feature("Cut-Extrude1", "Cut", data)])

    with pytest.raises(RuntimeError, match="type mismatch"):
        fe.edit_feature(_Adapter(model), "Cut-Extrude1", {"depth": 2}, _NULL)
    assert data.released == 1


def test_after_falls_back_to_the_changes_when_unreadable() -> None:
    data = _ExtrudeData()
    feature = _Feature("Boss-Extrude1", "Extrusion", data)
    model = _Model([feature])
    calls = {"n": 0}

    def definition() -> Any:
        calls["n"] += 1
        return data if calls["n"] == 1 else None

    feature.GetDefinition = definition  # type: ignore[method-assign]

    reply = fe.edit_feature(_Adapter(model), "Boss-Extrude1", {"depth": 7}, _NULL)

    assert reply["after"] == {"depth": 7}


# ---- rollback ------------------------------------------------------------------


def _tree() -> list[_Feature]:
    return [_Feature(n, "Extrusion", None) for n in ("Boss1", "Cut1", "Fillet1")]


@pytest.mark.parametrize(
    ("before", "after", "position", "rolled", "call"),
    [
        (None, "Cut1", "after Cut1", ["Fillet1"], (fe.ROLLBACK_AFTER, "Cut1")),
        (
            "Cut1",
            None,
            "before Cut1",
            ["Cut1", "Fillet1"],
            (fe.ROLLBACK_BEFORE, "Cut1"),
        ),
        (None, None, "the end", [], (fe.ROLLBACK_TO_END, "")),
    ],
)
def test_the_rollback_bar_moves(
    before: str | None, after: str | None, position: str, rolled: list[str], call: Any
) -> None:
    model = _Model(_tree())

    reply = fe.set_rollback(_Adapter(model), before, after)

    assert reply == {"position": position, "rolled_back": rolled}
    assert model.FeatureManager.calls == [call]


def test_a_rollback_to_a_missing_feature_or_refused() -> None:
    with pytest.raises(LookupError, match="'Nope' not found"):
        fe.set_rollback(_Adapter(_Model(_tree())), "Nope", None)
    with pytest.raises(
        RuntimeError, match="did not move the rollback bar after 'Cut1'"
    ):
        fe.set_rollback(_Adapter(_Model(_tree(), moves=False)), None, "Cut1")
    with pytest.raises(RuntimeError, match="to the end"):
        fe.set_rollback(_Adapter(_Model(_tree(), moves=False)), None, None)


def test_an_empty_tree_has_nothing_rolled_back() -> None:
    assert fe.rolled_back_features(_Adapter(_Model([]))) == []


# ---- sketches ------------------------------------------------------------------


def _sketch() -> SimpleNamespace:
    segments = [
        _Segment(0, _Point(0, 0), _Point(20, 0)),
        _Segment(1, _Point(20, 0), _Point(0, 20), _Point(0, 0)),
        _Segment(3),
    ]
    return SimpleNamespace(GetSketchSegments=lambda: segments)


def test_an_existing_sketch_opens_with_its_segments_numbered() -> None:
    sketch = _sketch()
    model = _Model([_Feature("Sketch2", "ProfileFeature", None)], sketch=sketch)
    adapter = _Adapter(model)

    reply = fe.open_sketch(adapter, "Sketch2")

    assert reply["sketch"] == "Sketch2"
    assert reply["segments"][0] == {
        "id": "Line_1",
        "type": "line",
        "start_mm": [0.0, 0.0],
        "end_mm": [20.0, 0.0],
        "construction": False,
    }
    assert reply["segments"][1]["center_mm"] == [0.0, 0.0]
    assert reply["segments"][2]["id"] == "Spline_3"
    assert adapter.currentSketch is sketch
    assert adapter.currentSketchManager.AddToDB is True
    assert "EditSketch" in model.calls


@pytest.mark.parametrize(
    ("model", "error", "fragment"),
    [
        (_Model([_Feature("Cut1", "Cut", None)]), ValueError, "not a sketch"),
        (
            _Model([_Feature("Sketch2", "ProfileFeature", None)]),
            RuntimeError,
            "did not open",
        ),
    ],
)
def test_a_sketch_that_cannot_open(
    model: _Model, error: type[Exception], fragment: str
) -> None:
    name = model.tree[0].Name
    with pytest.raises(error, match=None) as caught:
        fe.open_sketch(_Adapter(model), name)
    assert fragment in str(caught.value)


def test_a_sketch_that_cannot_be_selected() -> None:
    feature = _Feature("Sketch2", "ProfileFeature", None)
    feature.Select2 = lambda *_a: False  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="could not select sketch"):
        fe.open_sketch(_Adapter(_Model([feature])), "Sketch2")


def test_points_that_do_not_read_are_left_out() -> None:
    adapter = _Adapter(_Model([]))
    segment = _Segment(0, SimpleNamespace(X=0.01), None)

    assert fe.describe_segment(adapter, segment) == {
        "type": "line",
        "construction": False,
    }


def test_sketch_entities_are_deleted_by_id() -> None:
    model = _Model([])
    adapter = _Adapter(model)
    keep, drop = _Segment(0), _Segment(1)
    adapter._sketch_entities = {"Line_1": keep, "Arc_2": drop}

    reply = fe.delete_sketch_entities(adapter, ["Arc_2"])

    assert reply == {"deleted": ["Arc_2"], "remaining": ["Line_1"]}
    assert model.calls[-1] == "EditDelete"

    with pytest.raises(LookupError, match="Sketch entity Arc_9 not found"):
        fe.delete_sketch_entities(adapter, ["Arc_9"])
    keep.selectable = False
    with pytest.raises(RuntimeError, match="could not select Line_1"):
        fe.delete_sketch_entities(adapter, ["Line_1"])
