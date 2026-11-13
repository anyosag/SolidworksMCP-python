"""Editing an existing model in place (``feature_editing``)."""

from __future__ import annotations

import math
import sys
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
    def __init__(
        self,
        name: str,
        kind: str,
        data: Any,
        modify: bool = True,
        older: str | None = None,
    ) -> None:
        self.Name, self._kind, self._data, self._modify = name, kind, data, modify
        self._older = older  # GetTypeName: an Instant3D feature's real type
        self.rolled_back = False
        self.after: _Feature | None = None

    def GetTypeName2(self) -> str:  # noqa: N802
        return self._kind

    def GetTypeName(self) -> str | None:  # noqa: N802
        return self._older

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
        ("Shell", {"depth": 1}, "changes extrudes, cuts, revolves, fillets and"),
        ("Fillet", {"depth": 1}, "it takes edge_rules, edges, radius, not depth"),
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


@pytest.mark.parametrize(
    ("type_name", "older", "reported"),
    [
        ("Cut", None, "Cut"),
        ("ICE", "Cut", "Cut"),
        ("ICE", "CUT", "Cut"),
        ("ICE", "Extrusion", "Extrusion"),
        ("ICE", "Boss", "Extrusion"),
        ("ICE", None, "ICE"),
    ],
)
def test_a_cuts_depth_and_direction_change_and_read_back(
    type_name: str, older: str | None, reported: str
) -> None:
    """An Instant3D extrude, boss or cut, is "ICE"; GetTypeName names which."""
    data = _ExtrudeData()
    model = _Model([_Feature("Cut-Extrude1", type_name, data, older=older)])

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
    assert reply["type"] == reported
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
            _Feature("Cut-Extrude1", "Shell", _ExtrudeData()),
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


# ---- fillet and chamfer edges ------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "changes", "fragment"),
    [
        ("Chamfer", {"radius": 1}, "a Chamfer; it takes edge_rules, edges, not radius"),
        ("Cut", {"edges": "selection"}, "reverse_direction, not edges"),
        (
            "Fillet",
            {"edges": "selection", "edge_rules": {}},
            "Give edges or edge_rules, not both.",
        ),
        ("Fillet", {"edges": "all"}, "edges takes 'selection' (the edges selected"),
        ("Chamfer", {"edge_rules": ["top"]}, "edge_rules must be a select_edges"),
        ("Chamfer", {"edge_rules": {"sides": "top"}}, "unknown key(s) sides; it"),
        ("Chamfer", {"edge_rules": {"append": True}}, "unknown key(s) append"),
        ("Fillet", {"edge_rules": {"edge_type": "round"}}, "edge_rules: edge_type"),
        ("Fillet", {"edge_rules": {"face_point": 5}}, "the wrong type"),
        (
            "Fillet",
            {"edge_rules": {"any_of": [{"side": "top"}, {"color": "red"}]}},
            "edge_rules: any_of[1] has unknown key(s) color",
        ),
    ],
)
def test_edge_changes_a_feature_does_not_take(
    kind: str, changes: dict[str, Any], fragment: str
) -> None:
    assert fragment in (fe.check_changes(kind, changes, "F1") or "")


@pytest.mark.parametrize(
    ("kind", "changes"),
    [
        ("Fillet", {"edges": "selection", "radius": 2}),
        ("Fillet", {"edge_rules": {"edge_type": " Linear "}}),
        ("Chamfer", {"edge_rules": {"any_of": [{"side": "top"}, {"side": "-x"}]}}),
        ("Chamfer", {"edges": "selection"}),
    ],
)
def test_fillets_and_chamfers_take_new_edges(
    kind: str, changes: dict[str, Any]
) -> None:
    assert fe.check_changes(kind, changes, "F1") is None


def test_an_edge_query_is_put_as_select_edges_takes_it() -> None:
    assert fe.edge_query({"edge_type": " Linear ", "side": "top"}) == {
        "edge_type": "linear",
        "side": "top",
    }
    assert fe.edge_query({"side": "top"}) == {"side": "top"}


class _EdgeData:
    """``ISimpleFilletFeatureData2`` / ``IChamferFeatureData2`` with edges.

    ``keeps`` is how many of the edges put SolidWorks keeps (all when None).
    Without ``counts`` there is no ``GetEdgeCount``, so ``Edges`` is read;
    without ``readable`` that gives None too.
    """

    def __init__(
        self,
        edges: int = 1,
        keeps: int | None = None,
        counts: bool = True,
        manager: _Selection | None = None,
        readable: bool = True,
    ) -> None:
        self._edges: list[Any] = [object() for _ in range(edges)]
        self._keeps, self._manager, self._readable = keeps, manager, readable
        self.DefaultRadius = 0.001
        self.put: Any = None
        self.released = 0
        self.accessed = False
        if counts:
            self.GetEdgeCount = lambda: len(self._edges)

    @property
    def Edges(self) -> tuple[Any, ...] | None:  # noqa: N802
        return tuple(self._edges) if self._readable else None

    @Edges.setter
    def Edges(self, value: Any) -> None:  # noqa: N802
        self.put = value
        given = list(getattr(value, "value", value))
        self._edges = given[: self._keeps] if self._keeps is not None else given

    def AccessSelections(self, doc: Any, component: Any) -> bool:  # noqa: N802
        self.accessed = True
        if self._manager is not None:  # as SolidWorks may: the selection goes
            self._manager.entities.clear()
        return True

    def ReleaseSelectionAccess(self) -> None:  # noqa: N802
        self.released += 1


class _Selection:
    """``ISelectionMgr`` holding ``(type, object)`` entries."""

    def __init__(self, *entities: tuple[int, Any]) -> None:
        self.entities = list(entities)

    def GetSelectedObjectCount2(self, mark: int) -> int:  # noqa: N802
        return len(self.entities)

    def GetSelectedObjectType3(self, index: int, mark: int) -> int:  # noqa: N802
        return self.entities[index - 1][0]

    def GetSelectedObject6(self, index: int, mark: int) -> Any:  # noqa: N802
        return self.entities[index - 1][1]


def _given(value: Any) -> list[Any]:
    """The edges in a ``dispatch_array``: a VARIANT's value, or the list."""
    return list(getattr(value, "value", value))


def _part(feature: _Feature, selection: _Selection | None = None) -> _Model:
    model = _Model([feature])
    model.SelectionManager = selection or _Selection()  # type: ignore[attr-defined]
    return model


def test_a_fillet_takes_the_selected_edges_and_says_what_it_kept() -> None:
    """Probe 2: given its own top face's four edges, a fillet kept two."""
    edges = [object(), object(), object(), object()]
    selection = _Selection(
        (2, object()), *((fe.SELECTED_EDGE, edge) for edge in edges), (1, None)
    )
    data = _EdgeData(edges=1, keeps=2, manager=selection)
    model = _part(_Feature("Fillet1", "Fillet", data), selection)

    reply = fe.edit_feature(
        _Adapter(model), "Fillet1", {"edges": "selection", "radius": 2}, _NULL
    )

    assert _given(data.put) == edges  # gathered before AccessSelections cleared them
    assert reply["edges_before"] == 1
    assert reply["edges_given"] == 4
    assert reply["edges_after"] == 2
    assert (reply["before"], reply["after"]) == ({"radius": 1.0}, {"radius": 2.0})
    assert model.calls == ["rebuild"]


def test_new_edges_go_in_as_a_dispatch_array() -> None:
    pythoncom = pytest.importorskip("pythoncom")
    edge = object()

    put = fe.dispatch_array([edge])

    assert put.varianttype == pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH
    assert put.value == [edge]


def test_without_pywin32_the_edges_go_in_as_a_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pythoncom", None)
    edge = object()

    assert fe.dispatch_array((edge,)) == [edge]


def _cube_edges(size: float = 10.0) -> list[Any]:
    """The twelve straight edges of a cube from the origin, as ``IEdge`` fakes."""

    def vertex(point: list[float]) -> Any:
        return SimpleNamespace(GetPoint=lambda: [c / 1000 for c in point])

    line = SimpleNamespace(IsCircle=lambda: False, IsLine=lambda: True)
    edges = []
    for axis in range(3):
        others = [i for i in range(3) if i != axis]
        for a in (0.0, size):
            for b in (0.0, size):
                start = [0.0, 0.0, 0.0]
                start[others[0]], start[others[1]] = a, b
                end = list(start)
                end[axis] = size
                edges.append(
                    SimpleNamespace(
                        GetCurve=lambda: line,
                        GetStartVertex=lambda s=start: vertex(s),
                        GetEndVertex=lambda e=end: vertex(e),
                    )
                )
    return edges


def test_a_chamfer_moves_to_the_edges_a_rule_matches() -> None:
    """The top face's straight edges, without selecting anything."""
    cube = _cube_edges()
    data = _EdgeData(edges=1, counts=False)
    model = _part(_Feature("Chamfer1", "Chamfer", data))
    body = SimpleNamespace(GetEdges=lambda: cube)
    model.GetBodies2 = lambda *_a: [body]  # type: ignore[attr-defined]
    top = {"edge_type": "Linear", "inside_box": [[-1, 9, -1], [11, 11, 11]]}

    reply = fe.edit_feature(_Adapter(model), "Chamfer1", {"edge_rules": top}, _NULL)

    tops = [e for e in cube if abs(e.GetStartVertex().GetPoint()[1] - 0.01) < 1e-9]
    tops = [e for e in tops if abs(e.GetEndVertex().GetPoint()[1] - 0.01) < 1e-9]
    assert _given(data.put) == tops
    assert (reply["edges_before"], reply["edges_given"], reply["edges_after"]) == (
        1,
        4,
        4,
    )
    assert reply["before"] == reply["after"] == {}
    assert reply["type"] == "Chamfer"


@pytest.mark.parametrize(
    ("selection", "fragment"),
    [
        (_Selection(), "nothing is selected. Select its new edges first"),
        (
            _Selection((2, object()), (3, object())),
            "none of the 2 selected entities is an edge",
        ),
    ],
)
def test_no_selected_edge_leaves_the_fillet_as_it_was(
    selection: _Selection, fragment: str
) -> None:
    data = _EdgeData()
    model = _part(_Feature("Fillet1", "Fillet", data), selection)

    with pytest.raises(ValueError) as caught:
        fe.edit_feature(_Adapter(model), "Fillet1", {"edges": "selection"}, _NULL)

    assert str(caught.value).startswith(
        "No new edges for 'Fillet1', so it is unchanged: "
    )
    assert fragment in str(caught.value)
    assert not data.accessed and data.put is None
    assert model.calls == []


def test_a_rule_that_matches_nothing_leaves_the_chamfer_as_it_was() -> None:
    data = _EdgeData()
    model = _part(_Feature("Chamfer1", "Chamfer", data))
    model.GetBodies2 = lambda *_a: [  # type: ignore[attr-defined]
        SimpleNamespace(GetEdges=_cube_edges)
    ]

    with pytest.raises(ValueError) as caught:
        fe.edit_feature(
            _Adapter(model),
            "Chamfer1",
            {"edge_rules": {"edge_type": "circular"}},
            _NULL,
        )

    assert str(caught.value) == (
        "No new edges for 'Chamfer1', so it is unchanged: no matching edges found: "
        "the part has 12 edge(s); 0 pass edge_type."
    )
    assert not data.accessed


def test_a_refused_edge_change_releases_the_definition() -> None:
    edge = object()
    data = _EdgeData()
    feature = _Feature("Fillet1", "Fillet", data, modify=False)
    model = _part(feature, _Selection((fe.SELECTED_EDGE, edge)))

    with pytest.raises(RuntimeError, match="refused the change to 'Fillet1'"):
        fe.edit_feature(_Adapter(model), "Fillet1", {"edges": "selection"}, _NULL)
    assert data.released == 1


def test_edge_counts_that_do_not_read_are_none() -> None:
    edge = object()
    data = _EdgeData(counts=False, readable=False)
    feature = _Feature("Fillet1", "Fillet", data)
    model = _part(feature, _Selection((fe.SELECTED_EDGE, edge)))
    calls = {"n": 0}

    def definition() -> Any:
        calls["n"] += 1
        return data if calls["n"] == 1 else None

    feature.GetDefinition = definition  # type: ignore[method-assign]

    reply = fe.edit_feature(_Adapter(model), "Fillet1", {"edges": "selection"}, _NULL)

    assert (reply["edges_before"], reply["edges_given"], reply["edges_after"]) == (
        None,
        1,
        None,
    )
    assert reply["after"] == {}


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


def test_an_unknown_id_names_the_ids_the_sketch_has() -> None:
    adapter = _Adapter(_Model([]))
    adapter._sketch_entities = {f"Line_{n}": _Segment(0) for n in range(1, 41)}

    with pytest.raises(LookupError) as caught:
        fe.delete_sketch_entities(adapter, ["Line_50", "Arc_99"])

    first_30 = ", ".join(f"Line_{n}" for n in range(1, 31))
    assert str(caught.value) == (
        "Sketch entity Line_50, Arc_99 not found in the open sketch. The open "
        f"sketch has 40 ids; the first 30: {first_30}. Ids change each time a "
        "sketch is opened: use the ids in the latest edit_sketch reply (and the "
        "add_* replies since), or all: true to delete every entity."
    )


@pytest.mark.parametrize(
    ("known", "fragment"),
    [
        (["Line_1", "Arc_2"], "The open sketch has 2 ids: Line_1, Arc_2. Ids"),
        (["Line_1"], "The open sketch has one id: Line_1. Ids"),
        ([], "The open sketch has no entity ids. Ids"),
    ],
)
def test_the_not_found_message_for_a_short_sketch(
    known: list[str], fragment: str
) -> None:
    assert fragment in fe.missing_ids_message(["Line_5"], known)


def _open(adapter: _Adapter, *segments: _Segment) -> None:
    sketch = SimpleNamespace(GetSketchSegments=lambda: segments)
    adapter.currentSketchManager = SimpleNamespace(ActiveSketch=sketch)


def test_every_segment_of_the_open_sketch_is_deleted() -> None:
    model = _Model([])
    adapter = _Adapter(model)
    line, arc, no_id, side = _Segment(0), _Segment(1), _Segment(3), _Segment(0)
    _open(adapter, line, arc, no_id, side)
    adapter._sketch_entities = {
        "Line_1": line,
        "Arc_2": arc,
        "Rectangle_3": [side, _Segment(0)],
        "Dimension_4": object(),
    }
    adapter._sketch_entity_centers = {"Arc_2": [0.0, 0.0]}

    reply = fe.delete_all_sketch_entities(adapter)

    assert reply == {
        "deleted": ["Line_1", "Arc_2", "Rectangle_3"],
        "deleted_count": 4,
        "skipped": [],
        "remaining": [],
    }
    assert model.calls == ["clear", "EditDelete"]
    assert adapter._sketch_entities == {}
    assert adapter._sketch_entity_centers == {}


def test_a_segment_that_will_not_select_is_left_and_reported() -> None:
    model = _Model([])
    adapter = _Adapter(model)
    line, stuck, stuck_no_id = _Segment(0), _Segment(1), _Segment(3)
    stuck.selectable = stuck_no_id.selectable = False
    # No sketch manager: the sketch create_sketch or edit_sketch kept is used.
    adapter.currentSketch = SimpleNamespace(
        GetSketchSegments=lambda: (stuck, line, stuck_no_id)
    )
    adapter._sketch_entities = {"Arc_1": stuck, "Line_2": line}

    reply = fe.delete_all_sketch_entities(adapter)

    assert reply == {
        "deleted": ["Line_2"],
        "deleted_count": 1,
        "skipped": [
            {"id": "Arc_1", "type": "arc", "construction": False},
            {"id": None, "type": "spline", "construction": False},
        ],
        "remaining": ["Arc_1"],
    }
    assert adapter._sketch_entities == {"Arc_1": stuck}


def test_deleting_everything_needs_a_sketch_that_selects() -> None:
    model = _Model([])
    adapter = _Adapter(model)
    with pytest.raises(RuntimeError, match="No sketch is open"):
        fe.delete_all_sketch_entities(adapter)

    stuck = _Segment(0)
    stuck.selectable = False
    _open(adapter, stuck)
    with pytest.raises(RuntimeError, match="could not select any of the open"):
        fe.delete_all_sketch_entities(adapter)
    assert "EditDelete" not in model.calls


def test_an_empty_sketch_deletes_nothing_and_forgets_stale_ids() -> None:
    model = _Model([])
    adapter = _Adapter(model)
    _open(adapter)
    adapter._sketch_entities = {"Line_1": _Segment(0)}

    reply = fe.delete_all_sketch_entities(adapter)

    assert reply == {"deleted": [], "deleted_count": 0, "skipped": [], "remaining": []}
    assert "EditDelete" not in model.calls
    assert adapter._sketch_entities == {}
