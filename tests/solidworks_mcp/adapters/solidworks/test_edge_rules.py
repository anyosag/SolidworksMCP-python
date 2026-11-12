"""Tests for rule-based edge selection (``select_edges``).

Fake COM objects model a 60 x 40 x 10 mm block with a 4 mm hole at
(30, 20), like ``test_face_selection.py``. ``Cut-Extrude1`` is the hole: its
one face is the cylinder wall, whose edges are the two rims. ``Boss-Extrude1``
made the top face and the front face, which share the edge along y = 0.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import edge_rules as er
from solidworks_mcp.adapters.solidworks import limits
from solidworks_mcp.adapters.solidworks.selection import SolidWorksSelectionMixin

# ---- fakes -------------------------------------------------------------------


class _Curve:
    def __init__(self, kind: str, params: list[float] | None = None) -> None:
        self._kind = kind
        self.CircleParams = params

    def IsCircle(self) -> bool:  # noqa: N802
        return self._kind == "circle"

    def IsLine(self) -> bool:  # noqa: N802
        return self._kind == "line"


class _Vertex:
    def __init__(self, p_mm: tuple[float, float, float]) -> None:
        self._p = [c / 1000 for c in p_mm]

    def GetPoint(self) -> list[float]:  # noqa: N802
        return self._p


class _Edge:
    def __init__(self, curve: _Curve, a: Any = None, b: Any = None) -> None:
        self._curve, self._a, self._b = curve, a, b
        self.selected = 0

    def GetCurve(self) -> _Curve:  # noqa: N802
        return self._curve

    def GetStartVertex(self) -> _Vertex | None:  # noqa: N802
        return _Vertex(self._a) if self._a else None

    def GetEndVertex(self) -> _Vertex | None:  # noqa: N802
        return _Vertex(self._b) if self._b else None

    def Select4(self, _append: bool, _data: Any) -> bool:  # noqa: N802
        self.selected += 1
        return True


def _line(a: tuple[float, ...], b: tuple[float, ...]) -> _Edge:
    return _Edge(_Curve("line"), a, b)


def _rim(z_mm: float) -> _Edge:
    return _Edge(_Curve("circle", [0.03, 0.02, z_mm / 1000, 0, 0, 1, 0.004]))


class _Face:
    def __init__(self, normal: Any, box_mm: Any, edges: list[_Edge]) -> None:
        self.Normal = list(normal)
        self._box = [c / 1000 for c in box_mm]
        self._edges = edges

    def GetBox(self) -> list[float]:  # noqa: N802
        return self._box

    def GetArea(self) -> float:  # noqa: N802
        return 1e-3

    def GetEdges(self) -> list[_Edge]:  # noqa: N802
        return self._edges


#: The front edge on the top face: y = 0, z = 10, along x. The top face and
#: the front face both return it, as SolidWorks does.
_SHARED = _line((0, 0, 10), (60, 0, 10))
_TOP_LINES = [
    _SHARED,
    _line((60, 0, 10), (60, 40, 10)),
    _line((60, 40, 10), (0, 40, 10)),
    _line((0, 40, 10), (0, 0, 10)),
]
_TOP_RIM, _BOTTOM_RIM = _rim(10), _rim(0)
_FRONT_LINES = [
    _line((60, 0, 10), (0, 0, 10)),  # the shared edge, the other way round
    _line((0, 0, 0), (60, 0, 0)),
    _line((0, 0, 0), (0, 0, 10)),
    _line((60, 0, 0), (60, 0, 10)),
]
_TOP = _Face((0, 0, 1), (0, 0, 10, 60, 40, 10), [*_TOP_LINES, _TOP_RIM])
_FRONT = _Face((0, -1, 0), (0, 0, 0, 60, 0, 10), _FRONT_LINES)
_WALL = _Face((0, 0, 0), (26, 16, 0, 34, 24, 10), [_TOP_RIM, _BOTTOM_RIM])


class _SelMgr:
    def __init__(self) -> None:
        self.count = 0

    def CreateSelectData(self) -> str:  # noqa: N802
        return "select-data"

    def GetSelectedObjectCount2(self, _mark: int) -> int:  # noqa: N802
        return self.count


def _model(doc_type: int = 1, body_edges: list[_Edge] | None = None) -> SimpleNamespace:
    features = {
        "Boss-Extrude1": SimpleNamespace(GetFaces=lambda: [_TOP, _FRONT]),
        "Cut-Extrude1": SimpleNamespace(GetFaces=lambda: [_WALL]),
        "Sketch1": SimpleNamespace(GetFaces=lambda: None),
    }
    edges = (
        [*_TOP_LINES, *_FRONT_LINES[1:], _TOP_RIM, _BOTTOM_RIM]
        if body_edges is None
        else body_edges
    )
    body = SimpleNamespace(
        GetFaces=lambda: [_TOP, _FRONT, _WALL], GetEdges=lambda: edges
    )
    return SimpleNamespace(
        GetBodies2=lambda _t, _v: [body],
        GetType=lambda: doc_type,
        FeatureByName=features.get,
        SelectionManager=_SelMgr(),
        ClearSelection2=lambda _all: None,
    )


class _Harness(SolidWorksSelectionMixin):
    def __init__(self, model: Any) -> None:
        self.currentModel = model
        self.swApp = None

    def _handle_com_operation(self, name: str, operation: Any, *args: Any) -> Any:
        try:
            return AdapterResult(
                status=AdapterResultStatus.SUCCESS, data=operation(*args)
            )
        except Exception as exc:  # noqa: BLE001 - mirror the real adapter
            return AdapterResult(
                status=AdapterResultStatus.ERROR, error=f"Error in {name}: {exc}"
            )

    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001
            return default

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value


def _line_info(a: list[float], b: list[float]) -> dict[str, Any]:
    length = math.dist(a, b)
    return {"curve": "linear", "start_mm": a, "end_mm": b, "length_mm": length}


def _rim_info(z: float) -> dict[str, Any]:
    return {
        "curve": "circular",
        "center_mm": [30.0, 20.0, z],
        "axis": [0.0, 0.0, 1.0],
        "radius_mm": 4.0,
    }


# ---- pure rules ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "vector"),
    [("x", (1.0, 0.0, 0.0)), (" Y ", (0.0, 1.0, 0.0)), ([0, 0, 2], (0.0, 0.0, 1.0))],
)
def test_axis_vector_names_and_directions(
    value: Any, vector: tuple[float, ...]
) -> None:
    assert er.axis_vector(value) == vector


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ("w", "must be 'x', 'y', 'z'"),
        ([1, 0], "must be [x, y, z]"),
        ([0, 0, 0], "zero"),
    ],
)
def test_axis_vector_refuses_what_is_not_a_direction(value: Any, fragment: str) -> None:
    with pytest.raises(ValueError, match=None) as caught:
        er.axis_vector(value)
    assert fragment in str(caught.value)


@pytest.mark.parametrize(
    ("query", "fragment"),
    [
        ({"feature": "Cut1", "side": "top"}, "at most one of feature"),
        ({"face_point": [1, 2]}, "face_point must be [x, y, z]"),
        ({"side": "sideways"}, "Unknown side"),
        ({"edge_type": "curvy"}, "edge_type must be one of"),
        ({"parallel_to": "w"}, "parallel_to must be"),
        ({"inside_box": [[0, 0, 0]]}, "inside_box must be"),
        ({"inside_box": [[0, 0], [1, 1]]}, "inside_box must be"),
        ({"inside_box": [[5, 0, 0], [1, 1, 1]]}, "first corner must be its minimum"),
        ({"min_length": 5, "max_length": 2}, "min_length must not be more"),
    ],
)
def test_bad_queries_are_explained(query: dict[str, Any], fragment: str) -> None:
    assert fragment in (er.validate_edge_query(query) or "")


def test_a_full_query_is_accepted() -> None:
    query = {
        "feature": "Cut-Extrude1",
        "edge_type": "linear",
        "parallel_to": [0, 1, 0],
        "inside_box": [[0, 0, 0], [10, 10, 10]],
        "min_length": 1,
        "max_length": 5,
    }
    assert er.validate_edge_query(query) is None
    assert er.validate_edge_query({}) is None


def test_edge_geometry_helpers() -> None:
    line = _line_info([0, 0, 0], [0, 30, 0])
    assert er.edge_direction(line) == (0.0, 1.0, 0.0)
    assert er.edge_direction(_rim_info(0)) is None
    assert er.edge_direction(_line_info([1, 1, 1], [1, 1, 1])) is None
    assert er.edge_length(line) == 30.0
    assert er.edge_length(_rim_info(0)) == pytest.approx(8 * math.pi)
    assert er.edge_length({"curve": "other"}) is None
    assert er.edge_extent(_rim_info(10)) == ([26.0, 16.0, 10.0], [34.0, 24.0, 10.0])
    assert er.edge_extent({"curve": "other"}) is None


def test_each_rule_narrows_and_is_counted() -> None:
    edges = [
        (None, _line_info([0, 0, 10], [60, 0, 10])),  # along x, 60 long
        (None, _line_info([0, 0, 0], [0, 40, 0])),  # along y, 40 long
        (None, _line_info([10, 10, 0], [10, 15, 0])),  # along y, 5 long
        (None, _rim_info(0)),
    ]

    kept, counts = er.filter_edges(
        edges,
        {
            "edge_type": "linear",
            "parallel_to": "y",
            "inside_box": [[0, 0, 0], [20, 20, 1]],
            "max_length": 10,
        },
    )

    assert [info["length_mm"] for _, info in kept] == [5.0]
    assert counts == {
        "candidates": 4,
        "edge_type": 3,
        "parallel_to": 2,
        "inside_box": 1,
        "length": 1,
    }


def test_parallel_tolerance_and_circles_outside_a_box() -> None:
    tilted = (None, _line_info([0, 0, 0], [100, 1, 0]))  # 0.57 degrees off x
    rim = (None, _rim_info(0))

    assert er.filter_edges([tilted], {"parallel_to": "x"})[0] == [tilted]
    assert (
        er.filter_edges([tilted], {"parallel_to": "x", "parallel_tolerance_deg": 0.1})[
            0
        ]
        == []
    )
    # The rim reaches x 26..34: a box to x = 30 cuts it, so it is outside.
    assert er.filter_edges([rim], {"inside_box": [[0, 0, -1], [30, 40, 1]]})[0] == []
    assert er.filter_edges([rim], {"min_length": 20})[0] == [rim]
    assert er.filter_edges([(None, {"curve": "other"})], {"min_length": 1})[0] == []
    assert (
        er.filter_edges(
            [(None, {"curve": "other"})], {"inside_box": [[0] * 3, [1] * 3]}
        )[0]
        == []
    )


@pytest.mark.parametrize(
    ("query", "source"),
    [
        ({"feature": "Cut-Extrude1"}, "feature 'Cut-Extrude1'"),
        ({"face_point": [1, 2, 3]}, "the face at [1, 2, 3] mm"),
        ({"side": "top"}, "the top face"),
        ({"plane": "Top Plane"}, "the face(s) on 'Top Plane'"),
        ({}, "the part"),
    ],
)
def test_sources_in_words(query: dict[str, Any], source: str) -> None:
    assert er.describe_source(query) == source


def test_an_empty_result_names_the_rule_that_emptied_it() -> None:
    message = er.no_match_message(
        {"feature": "Cut-Extrude1"},
        {"candidates": 2, "edge_type": 0},
    )

    assert message == (
        "No matching edges found: feature 'Cut-Extrude1' has 2 edge(s); 0 pass edge_type."
    )


def test_the_same_edge_either_way_round_has_one_key() -> None:
    forward = _line_info([0, 0, 10], [60, 0, 10])
    backward = _line_info([60, 0, 10], [0, 0, 10])

    assert er.edge_key(forward) == er.edge_key(backward)
    assert er.edge_key(_rim_info(0)) != er.edge_key(_rim_info(10))
    assert er.edge_key({"curve": "other"}) is None


# ---- COM gathering -------------------------------------------------------------


def test_a_features_edges_are_its_faces_edges_once_each() -> None:
    selector = er.EdgeRuleSelector(_Harness(_model()))

    edges = selector.candidates({"feature": "Boss-Extrude1"})

    # 5 top edges + 4 front edges, less the one they share.
    assert len(edges) == 8
    assert sum(1 for handle, _ in edges if handle is _SHARED) == 1


@pytest.mark.parametrize(
    ("query", "fragment"),
    [
        ({"feature": "Nope"}, "Feature 'Nope' not found"),
        ({"feature": "Sketch1"}, "has no faces in the body"),
    ],
)
def test_a_feature_source_must_have_faces(query: dict[str, Any], fragment: str) -> None:
    selector = er.EdgeRuleSelector(_Harness(_model()))

    with pytest.raises(LookupError, match=None) as caught:
        selector.candidates(query)
    assert fragment in str(caught.value)


def test_a_face_source_and_the_whole_part() -> None:
    selector = er.EdgeRuleSelector(_Harness(_model()))

    assert len(selector.candidates({"side": "+z"})) == 5
    assert len(selector.candidates({})) == 9


def test_an_edgeless_part_is_an_error() -> None:
    selector = er.EdgeRuleSelector(_Harness(_model(body_edges=[])))

    with pytest.raises(LookupError, match="no solid body edges"):
        selector.candidates({})


def test_edges_without_geometry_are_never_merged() -> None:
    splines = [_Edge(_Curve("spline")), _Edge(_Curve("spline"))]
    selector = er.EdgeRuleSelector(_Harness(_model(body_edges=splines)))

    assert len(selector.candidates({})) == 2


# ---- the adapter method ------------------------------------------------------


async def test_the_cut_rims_are_selected() -> None:
    harness = _Harness(_model())

    result = await harness.select_edges(
        {"feature": "Cut-Extrude1", "edge_type": "circular"}
    )

    assert result.is_success, result.error
    data = result.data or {}
    assert data["source"] == "feature 'Cut-Extrude1'"
    assert data["selected_edges"] == 2
    assert data["matched"] == {"candidates": 2, "edge_type": 2}
    assert _TOP_RIM.selected and _BOTTOM_RIM.selected


async def test_straight_edges_along_y_in_the_whole_part() -> None:
    harness = _Harness(_model())

    result = await harness.select_edges({"parallel_to": "y"}, append=True)

    assert result.is_success
    assert {tuple(e["start_mm"]) for e in (result.data or {})["edges"]} == {
        (60.0, 0.0, 10.0),
        (0.0, 40.0, 10.0),
    }


async def test_no_match_says_which_rule_removed_them() -> None:
    harness = _Harness(_model())

    result = await harness.select_edges({"side": "+z", "min_length": 100})

    assert result.is_error
    assert result.error == (
        "No matching edges found: the +z face has 5 edge(s); 0 pass length."
    )


@pytest.mark.parametrize(
    ("model", "query", "fragment"),
    [
        (_model(), {"side": "up"}, "Unknown side"),
        (None, {}, "No active model"),
        (_model(doc_type=2), {}, "select_edges requires an active part document"),
    ],
)
async def test_select_edges_refusals(
    model: Any, query: dict[str, Any], fragment: str
) -> None:
    result = await _Harness(model).select_edges(query)

    assert fragment in (result.error or "")


# ---- any_of: several rules in one call -------------------------------------------


def test_any_of_rules_are_laid_over_the_shared_keys() -> None:
    query = {
        "feature": "Boss-Extrude1",
        "edge_type": "all",
        "any_of": [{"parallel_to": "x"}, {"edge_type": " Circular ", "side": None}],
    }

    assert er.expand_query(query) == [
        {"feature": "Boss-Extrude1", "edge_type": "all", "parallel_to": "x"},
        {"feature": "Boss-Extrude1", "edge_type": "circular", "side": None},
    ]
    assert er.expand_query({"side": "top", "any_of": None}) == [{"side": "top"}]
    assert er.validate_edge_query(query) is None


@pytest.mark.parametrize(
    ("any_of", "fragment"),
    [
        ([], "any_of must be a list of 1 to 20 rules"),
        ([{}] * 21, "any_of must be a list of 1 to 20 rules"),
        ("top", "any_of must be a list"),
        ([{}, "top"], "any_of[1] must be a rule"),
        (
            [{"box": [0, 0, 0]}],
            "any_of[0] has unknown key(s) box; a rule takes feature",
        ),
        ([{}, {"side": "top"}], "any_of[1]: Give at most one of feature"),
        ([{"edge_type": "curvy"}], "any_of[0]: edge_type must be one of"),
    ],
)
def test_bad_any_of_rules_are_explained(any_of: Any, fragment: str) -> None:
    query = {"feature": "Boss-Extrude1", "any_of": any_of}

    assert fragment in (er.validate_edge_query(query) or "")


def test_rules_on_one_source_read_its_edges_once_and_keep_each_edge_once() -> None:
    """Cellvis: six select_edges calls on one part took about 70 s."""
    reads: list[dict[str, Any]] = []
    x_line = (None, _line_info([0, 0, 10], [60, 0, 10]))
    y_line = (None, _line_info([0, 0, 0], [0, 40, 0]))
    rim = (None, _rim_info(0))

    def candidates(rule: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
        reads.append(rule)
        return [x_line, y_line, rim] if rule.get("feature") else [rim]

    rules = er.expand_query(
        {
            "feature": "Boss-Extrude1",
            "any_of": [
                {"parallel_to": "x"},
                {"edge_type": "linear"},  # the x line again, and the y line
                {"side": "top", "feature": None},
            ],
        }
    )
    kept, counts = er.match_rules(rules, candidates)

    assert [info for _edge, info in kept] == [x_line[1], y_line[1], rim[1]]
    assert len(reads) == 2  # the feature once, the face once
    assert counts == [
        {"candidates": 3, "parallel_to": 1},
        {"candidates": 3, "edge_type": 2},
        {"candidates": 1},
    ]


def test_edges_without_a_key_are_kept_once_per_reading() -> None:
    spline = (None, {"curve": "other"})

    kept, _counts = er.match_rules([{}, {"edge_type": "all"}], lambda _r: [spline])

    assert kept == [spline]


def test_no_rule_matching_names_each_rules_counts() -> None:
    rules = [{"feature": "Cut-Extrude1"}, {"side": "top"}]
    counts = [{"candidates": 2, "length": 0}, {"candidates": 5, "inside_box": 0}]

    assert er.no_match_message_rules(rules, counts) == (
        "No matching edges found for any rule: rule 0: feature 'Cut-Extrude1' has "
        "2 edge(s); 0 pass length | rule 1: the top face has 5 edge(s); 0 pass "
        "inside_box."
    )
    assert er.no_match_message_rules(rules[:1], counts[:1]) == er.no_match_message(
        rules[0], counts[0]
    )
    assert er.describe_sources([*rules, {"feature": "Cut-Extrude1"}]) == (
        "feature 'Cut-Extrude1' and the top face"
    )


async def test_any_of_selects_edges_in_two_places_in_one_call() -> None:
    harness = _Harness(_model())

    result = await harness.select_edges(
        {
            "feature": "Boss-Extrude1",
            "any_of": [
                {"inside_box": [[-1, -1, 9], [61, 1, 11]]},  # the shared front edge
                {"inside_box": [[59, -1, -1], [61, 1, 11]]},  # the right front edge
            ],
        }
    )

    assert result.is_success, result.error
    data = result.data or {}
    assert data["selected_edges"] == 2
    assert data["source"] == "feature 'Boss-Extrude1'"
    assert data["matched"] == {
        "rules": [
            {"candidates": 8, "inside_box": 1},
            {"candidates": 8, "inside_box": 1},
        ]
    }


async def test_any_of_with_no_match_names_each_rule() -> None:
    result = await _Harness(_model()).select_edges(
        {
            "any_of": [
                {"side": "+z", "min_length": 100},
                {"feature": "Cut-Extrude1", "edge_type": "linear"},
            ]
        }
    )

    assert result.error == (
        "No matching edges found for any rule: rule 0: the +z face has 5 edge(s); "
        "0 pass length | rule 1: feature 'Cut-Extrude1' has 2 edge(s); 0 pass "
        "edge_type."
    )


def test_reading_edges_stops_when_the_client_has_gone() -> None:
    selector = er.EdgeRuleSelector(_Harness(_model()))
    limits.mark_client_gone("test")

    with pytest.raises(limits.OperationStopped, match="Stopped reading edges"):
        selector.candidates({})
