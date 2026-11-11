"""Coordinate edge/face picks: one pass over the body, however many points.

``_BodyEntityPicker`` used to measure every edge (``GetClosestPointOn``) for
every point, so a 133-edge fillet cost 133 x E round trips. A picker told to
expect many picks now reads a bounding box per edge once and measures only
the edges whose box could hold a closer point. These tests check that the
answer is exactly the one measuring every edge gives, and count the round
trips the fakes see.

Fakes model a 40 x 20 x 12 mm plate (z from -6 to +6) with a hole rim, a
quarter arc, a tilted arc and an edge of an unknown curve type. Every member
call and every ``_FlagAsMethod`` counts as one round trip.
"""

from __future__ import annotations

import math
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import features

Point = tuple[float, float, float]

# ---- fakes -----------------------------------------------------------------


class _Log:
    """Round trips seen by the fakes, by member name, plus an event order."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.events: list[str] = []


class _Dispatch:
    """A fake dispatch whose member calls and flags are all counted."""

    def __init__(self, log: _Log) -> None:
        self._log = log

    def _FlagAsMethod(self, name: str) -> None:
        self._log.calls[f"flag:{name}"] += 1

    def _count(self, name: str) -> None:
        self._log.calls[name] += 1


class _Vertex(_Dispatch):
    def __init__(self, log: _Log, point: Point | None) -> None:
        super().__init__(log)
        self.point = point

    def GetPoint(self) -> list[float] | None:
        self._count("GetPoint")
        return None if self.point is None else list(self.point)


class _Curve(_Dispatch):
    def __init__(self, log: _Log, kind: str, circle: list[float] | None) -> None:
        super().__init__(log)
        self.kind, self.circle = kind, circle

    def IsLine(self) -> bool:
        self._count("IsLine")
        return self.kind == "line"

    def IsCircle(self) -> bool:
        self._count("IsCircle")
        return self.kind == "circle"

    @property
    def CircleParams(self) -> list[float] | None:
        self._count("CircleParams")
        return self.circle


class _Edge(_Dispatch):
    """Selection, counting and the curve/vertex reads shared by every edge."""

    curve_kind = "other"
    circle: list[float] | None = None

    def __init__(self, log: _Log, name: str) -> None:
        super().__init__(log)
        self.name = name
        self.selected_with: list[tuple[bool, Any]] = []
        self.ends: tuple[Point | None, Point | None] | None = None

    def GetCurve(self) -> _Curve:
        self._count("GetCurve")
        return _Curve(self._log, self.curve_kind, self.circle)

    def GetStartVertex(self) -> _Vertex | None:
        self._count("GetStartVertex")
        return None if self.ends is None else _Vertex(self._log, self.ends[0])

    def GetEndVertex(self) -> _Vertex | None:
        self._count("GetEndVertex")
        return None if self.ends is None else _Vertex(self._log, self.ends[1])

    def GetClosestPointOn(self, x: float, y: float, z: float) -> list[float]:
        self._count("GetClosestPointOn")
        return [*self.closest((x, y, z)), 0.0]

    def closest(self, p: Point) -> Point:
        raise NotImplementedError

    def Select4(self, append: bool, data: Any) -> bool:
        self._count("Select4")
        self._log.events.append(f"Select4:{self.name}")
        self.selected_with.append((append, data))
        return True


class _Line(_Edge):
    """A straight edge from ``a`` to ``b`` (metres)."""

    curve_kind = "line"

    def __init__(self, log: _Log, name: str, a: Point, b: Point) -> None:
        super().__init__(log, name)
        self.a, self.b = a, b
        self.ends = (a, b)

    def closest(self, p: Point) -> Point:
        ab = [q - r for q, r in zip(self.b, self.a, strict=True)]
        ap = [q - r for q, r in zip(p, self.a, strict=True)]
        t = sum(u * v for u, v in zip(ab, ap, strict=True)) / sum(u * u for u in ab)
        t = min(1.0, max(0.0, t))
        return tuple(a + t * d for a, d in zip(self.a, ab, strict=True))

    def point_at(self, t: float) -> Point:
        return tuple(a + t * (b - a) for a, b in zip(self.a, self.b, strict=True))


class _Other(_Line):
    """A straight edge whose curve SolidWorks reports as neither line nor arc."""

    curve_kind = "other"


def _unit(v: Point) -> Point:
    length = math.sqrt(sum(c * c for c in v))
    return tuple(c / length for c in v)


def _cross(a: Point, b: Point) -> Point:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


class _Arc(_Edge):
    """An arc of ``sweep`` radians from ``start``; a full circle has no vertices."""

    curve_kind = "circle"

    def __init__(
        self,
        log: _Log,
        name: str,
        center: Point,
        radius: float,
        axis: Point = (0.0, 0.0, 1.0),
        ref: Point = (1.0, 0.0, 0.0),
        start: float = 0.0,
        sweep: float = 2 * math.pi,
    ) -> None:
        super().__init__(log, name)
        self.center, self.radius = center, radius
        self.n = _unit(axis)
        self.u = _unit(ref)
        self.v = _cross(self.n, self.u)
        self.start, self.sweep = start, sweep
        self.circle = [*center, *self.n, radius]
        if sweep < 2 * math.pi:
            self.ends = (self.point_at(start), self.point_at(start + sweep))

    def point_at(self, angle: float) -> Point:
        cos, sin = math.cos(angle), math.sin(angle)
        return tuple(
            c + self.radius * (cos * u + sin * v)
            for c, u, v in zip(self.center, self.u, self.v, strict=True)
        )

    def closest(self, p: Point) -> Point:
        q = [a - c for a, c in zip(p, self.center, strict=True)]
        angle = math.atan2(
            sum(a * b for a, b in zip(q, self.v, strict=True)),
            sum(a * b for a, b in zip(q, self.u, strict=True)),
        )
        relative = (angle - self.start) % (2 * math.pi)
        if relative <= self.sweep:
            return self.point_at(self.start + relative)
        ends = [self.point_at(self.start), self.point_at(self.start + self.sweep)]
        return min(ends, key=lambda e: math.dist(e, p))


class _FixedEdge(_Edge):
    """An arc-typed edge whose closest point is fixed (for exact ties)."""

    curve_kind = "circle"

    def __init__(self, log: _Log, name: str, circle: list[float], at: Point) -> None:
        super().__init__(log, name)
        self.circle, self.at = circle, at

    def closest(self, p: Point) -> Point:
        return self.at


class _Face(_Dispatch):
    """A planar face: a box ``lo``..``hi`` flat on one axis, with its edges."""

    def __init__(self, log: _Log, name: str, lo: Point, hi: Point, edges=()) -> None:
        super().__init__(log)
        self.name, self.lo, self.hi, self.edges = name, lo, hi, list(edges)
        self.box: list[float] | None = [*hi, *lo]  # corners in either order

    def GetBox(self) -> list[float] | None:
        self._count("GetBox")
        return self.box

    def GetClosestPointOn(self, x: float, y: float, z: float) -> list[float]:
        self._count("GetClosestPointOn")
        clamp = [
            min(h, max(lo, c))
            for lo, h, c in zip(self.lo, self.hi, (x, y, z), strict=True)
        ]
        return [*clamp, 0.0, 0.0]

    def GetEdges(self) -> tuple:
        self._count("GetEdges")
        return tuple(self.edges)

    def Select4(self, _append: bool, _data: Any) -> bool:
        self._count("Select4")
        self._log.events.append(f"Select4:{self.name}")
        return True


class _Body(_Dispatch):
    def __init__(self, log: _Log, edges=(), faces=()) -> None:
        super().__init__(log)
        self.edges, self.faces = list(edges), list(faces)

    def GetEdges(self) -> tuple:
        self._count("GetEdges")
        return tuple(self.edges)

    def GetFaces(self) -> tuple:
        self._count("GetFaces")
        return tuple(self.faces)


class _SelectionManager(_Dispatch):
    def __init__(self, log: _Log, made: bool = True) -> None:
        super().__init__(log)
        self.made = made

    def CreateSelectData(self) -> Any:
        self._count("CreateSelectData")
        return SimpleNamespace(Mark=0) if self.made else None


class _Extension(_Dispatch):
    def __init__(self, log: _Log, named: set[str]) -> None:
        super().__init__(log)
        self.named = named

    def SelectByID2(self, name: str, kind: str, *_rest: Any) -> bool:
        self._count("SelectByID2")
        self._log.events.append(f"SelectByID2:{name}")
        return name in self.named


class _Model(_Dispatch):
    def __init__(self, log: _Log, body: _Body, named: set[str] | None = None) -> None:
        super().__init__(log)
        self.body = body
        self.manager = _SelectionManager(log)
        self.Extension = _Extension(log, named or set())
        self.counts = [7, 8]
        self.FeatureManager = SimpleNamespace(
            GetFeatureCount=lambda _top: self.counts.pop(0) if self.counts else None,
            InsertFeatureChamfer=self._chamfer,
        )

    @property
    def SelectionManager(self) -> _SelectionManager:
        self._count("SelectionManager")
        return self.manager

    def GetBodies2(self, _type: int, _visible: bool) -> tuple:
        self._count("GetBodies2")
        return (self.body,)

    def ForceRebuild3(self, top_only: bool) -> bool:
        self._count("ForceRebuild3")
        self._log.events.append(f"ForceRebuild3:{top_only}")
        return True

    def ClearSelection2(self, _all: bool) -> bool:
        self._count("ClearSelection2")
        self._log.events.append("ClearSelection2")
        return True

    def FeatureFillet3(self, *_args: Any) -> int:
        self._count("FeatureFillet3")
        return 1

    def _chamfer(self, *_args: Any) -> Any:
        self._count("InsertFeatureChamfer")
        return SimpleNamespace(Name="Chamfer1")


class _Adapter:
    """Just what the picker and the fillet/chamfer impls use (SW 2026)."""

    def __init__(self, model: _Model) -> None:
        self.currentModel = model
        self.swApp = SimpleNamespace(RevisionNumber="34.0.0")

    def _handle_com_operation(self, _name: str, callback: Any) -> AdapterResult:
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, callback: Any, default: Any = None) -> Any:
        try:
            return callback()
        except Exception:
            return default

    def _attempt_with_error(self, callback: Any) -> tuple[Any, str | None]:
        try:
            return callback(), None
        except Exception as exc:
            return None, str(exc)

    def _get_attr_or_call(self, obj: Any, name: str, default: Any = None) -> Any:
        return getattr(obj, name, default)

    def _get_feature_id(self, feature: Any) -> str:
        return ""


def _adapter(edges=(), faces=(), named: set[str] | None = None) -> _Adapter:
    log = _Log()
    edges = list(edges)
    faces = list(faces)
    for item in [*edges, *faces]:
        item._log = log
    model = _Model(log, _Body(log, edges, faces), named)
    adapter = _Adapter(model)
    adapter.log = log
    return adapter


def _plate(log: _Log | None = None) -> list[_Edge]:
    """The plate's 12 edges, a hole rim, a quarter arc, a tilted arc, a spline."""
    log = log or _Log()
    edges: list[_Edge] = []
    for z in (0.006, -0.006):
        tag = "front" if z > 0 else "back"
        corners = [(0.0, 0.0, z), (0.04, 0.0, z), (0.04, 0.02, z), (0.0, 0.02, z)]
        for i, side in enumerate(("bottom", "right", "top", "left")):
            edges.append(_Line(log, f"{tag}-{side}", corners[i], corners[(i + 1) % 4]))
    for x, y in ((0.0, 0.0), (0.04, 0.0), (0.04, 0.02), (0.0, 0.02)):
        edges.append(_Line(log, f"depth-{x}-{y}", (x, y, 0.006), (x, y, -0.006)))
    edges.append(_Arc(log, "hole-rim", (0.02, 0.01, 0.006), 0.004))
    edges.append(_Arc(log, "quarter", (0.033, 0.013, -0.006), 0.003, sweep=math.pi / 2))
    edges.append(
        _Arc(
            log,
            "tilted",
            (0.01, 0.01, 0.0),
            0.0025,
            axis=(1.0, 1.0, 1.0),
            ref=(1.0, -1.0, 0.0),
            start=0.3,
            sweep=4.0,
        )
    )
    edges.append(_Other(log, "spline", (0.005, 0.004, -0.006), (0.012, 0.016, 0.006)))
    return edges


def _points_on(edge: _Edge) -> list[Point]:
    """Points on ``edge``: its ends (corners, where edges tie) and inside."""
    if isinstance(edge, _Arc):
        return [edge.point_at(edge.start + f * edge.sweep) for f in (0, 0.3, 0.5, 1)]
    return [edge.point_at(t) for t in (0.0, 0.25, 0.5, 0.9, 1.0)]


def _many_picks() -> dict[str, int]:
    return {"GetEdges": features._INDEX_MIN_PICKS["GetEdges"]}


# ---- same answer as measuring every edge --------------------------------------


def test_box_search_picks_exactly_what_measuring_every_edge_picks() -> None:
    """Every point - on edges, at corners where three edges tie, slightly off
    an edge, and nowhere near one - resolves to the same edge and distance."""
    edges = _plate()
    points: list[Point] = []
    for edge in edges:
        for p in _points_on(edge):
            points += [p, (p[0] + 3e-4, p[1], p[2]), (p[0], p[1] - 2e-4, p[2] + 2e-4)]
    points += [(0.02, 0.01, 0.0), (0.03, 0.005, 0.001), (-0.01, 0.03, 0.02)]

    every = features._BodyEntityPicker(_adapter(edges))
    boxed = features._BodyEntityPicker(_adapter(edges), _many_picks())

    for p in points:
        expected = every.nearest("GetEdges", p)
        got = boxed.nearest("GetEdges", p)
        assert got is not None and expected is not None
        assert (got[0].name, got[1]) == (expected[0].name, expected[1]), p


@pytest.mark.parametrize("picks", [None, {"GetEdges": 20}])
def test_an_exact_tie_goes_to_the_first_edge_in_body_order(picks) -> None:
    """The arc's box holds the point, so the box search measures it first;
    the line, equally close, still wins because it comes first in the body."""
    log = _Log()
    p = (0.0, 0.0003, 0.0)
    line = _Line(log, "line", (-0.01, 0.0, 0.0), (0.01, 0.0, 0.0))
    arc = _FixedEdge(log, "arc", [*p, 0.0, 0.0, 1.0, 0.0003], (0.0003, 0.0003, 0.0))
    assert math.dist(line.closest(p), p) == math.dist(arc.at, p)  # a true tie

    for order, winner in (([line, arc], "line"), ([arc, line], "arc")):
        picker = features._BodyEntityPicker(_adapter(order), picks)
        entity, distance = picker.nearest("GetEdges", p)
        assert (entity.name, distance) == (winner, 0.0003)


def test_a_point_on_no_edge_reports_the_same_distance_either_way() -> None:
    edges = _plate()
    adapter = _adapter(edges)
    picker = features._BodyEntityPicker(adapter, _many_picks())

    with pytest.raises(LookupError, match=r"nearest is 2\.000 mm away"):
        features._select_edge_by_coord(
            adapter, 0.02, -0.002, 0.006, append=False, picker=picker
        )
    with pytest.raises(LookupError, match=r"nearest is 2\.000 mm away"):
        features._select_edge_by_coord(_adapter(edges), 0.02, -0.002, 0.006, False)
    assert not any(e.selected_with for e in edges)


# ---- the cost: one pass over the edges -------------------------------------------


def _grid(log: _Log, count: int) -> list[_Edge]:
    """``count`` separate 4 mm edges, 10 mm apart, alternating line and arc."""
    edges: list[Any] = []
    for i in range(count):
        x, y = (i % 20) * 0.01, (i // 20) * 0.01
        if i % 2:
            edges.append(_Arc(log, f"e{i}", (x, y, 0.0), 0.002, sweep=math.pi))
        else:
            edges.append(_Line(log, f"e{i}", (x, y, 0.0), (x + 0.004, y, 0.0)))
    return edges


def test_133_picks_over_300_edges_read_each_edge_once() -> None:
    """The reported case: 133 points used to cost 133 x 300 closest-point
    queries (and as many flags); now one box read per edge and about one
    query per point."""
    edges = _grid(_Log(), 300)
    targets = edges[:133]
    adapter = _adapter(edges)
    calls = adapter.log.calls
    specs = [",".join(str(c) for c in _points_on(e)[2]) for e in targets]

    result = features._add_fillet_impl(adapter, 1.0, specs)

    assert result.is_success, result.error
    assert [e.selected_with[0][0] for e in targets] == [False] + [True] * 132
    assert not any(e.selected_with for e in edges[133:])
    assert calls["GetBodies2"] == calls["GetEdges"] == 1
    assert calls["ForceRebuild3"] == calls["FeatureFillet3"] == 1
    assert calls["GetCurve"] == 300  # one box read per edge
    assert calls["GetClosestPointOn"] <= 2 * 133  # was 133 * 300 = 39 900
    assert calls["flag:GetClosestPointOn"] <= calls["GetClosestPointOn"]
    assert calls["CreateSelectData"] == calls["SelectionManager"] == 1
    assert calls["Select4"] == calls["flag:Select4"] == 133
    assert sum(calls.values()) < 300 * 20 + 133 * 6


def test_few_picks_skip_the_boxes_and_flag_each_edge_once() -> None:
    """Below the threshold every edge is measured, as before, but each edge
    is flagged once rather than once per point."""
    edges = _grid(_Log(), 40)
    adapter = _adapter(edges)
    picker = features._BodyEntityPicker(adapter, {"GetEdges": 3})

    for edge in edges[:3]:
        assert picker.nearest("GetEdges", _points_on(edge)[1])[0] is edge

    calls = adapter.log.calls
    assert calls["GetCurve"] == 0
    assert calls["GetClosestPointOn"] == 3 * 40
    assert calls["flag:GetClosestPointOn"] == 40


def test_the_threshold_is_where_box_reads_start() -> None:
    edges = _grid(_Log(), 4)
    below = _adapter(edges)
    features._BodyEntityPicker(below, {"GetEdges": 19}).nearest("GetEdges", (0, 0, 0))
    at = _adapter(edges)
    features._BodyEntityPicker(at, {"GetEdges": 20}).nearest("GetEdges", (0, 0, 0))

    assert below.log.calls["GetCurve"] == 0
    assert at.log.calls["GetCurve"] == 4


def test_edges_without_a_box_are_always_measured() -> None:
    """An unknown curve type, or geometry that cannot be read, has no box, so
    no point can rule it out."""
    log = _Log()
    near = _Line(log, "near", (0.0, 0.0, 0.0), (0.01, 0.0, 0.0))
    unknown = _Other(log, "unknown", (0.5, 0.5, 0.5), (0.6, 0.5, 0.5))
    no_curve = _Line(log, "no-curve", (0.7, 0.0, 0.0), (0.8, 0.0, 0.0))
    no_curve.GetCurve = lambda: None
    adapter = _adapter([near, unknown, no_curve])
    picker = features._BodyEntityPicker(adapter, _many_picks())

    for p in ((0.005, 0.0, 0.0), (0.002, 0.0, 0.0)):
        assert picker.nearest("GetEdges", p)[0] is near

    # "near" each time, the two box-less edges each time: 2 x 3.
    assert adapter.log.calls["GetClosestPointOn"] == 6


def _busy(*_point: float) -> list[float]:
    raise RuntimeError("busy")


def test_edges_whose_closest_point_is_unreadable_are_skipped() -> None:
    log = _Log()
    broken = _Line(log, "broken", (0.0, 0.0, 0.0), (0.01, 0.0, 0.0))
    broken.GetClosestPointOn = _busy
    short = _Line(log, "short", (0.0, 0.0, 0.0), (0.01, 0.0, 0.0))
    short.GetClosestPointOn = lambda *_point: [0.0, 0.0]
    edge = _Line(log, "edge", (0.0, 0.0, 0.0), (0.01, 0.0, 0.0))
    picker = features._BodyEntityPicker(_adapter([broken, short, edge]), _many_picks())

    entity, distance = picker.nearest("GetEdges", (0.005, 0.0, 0.0))

    assert (entity.name, distance) == ("edge", 0.0)


# ---- fillet and chamfer: one picker, one rebuild, one body walk ----------------------


def test_fillet_rebuilds_once_before_anything_is_selected() -> None:
    """A rebuild clears the selection, so it runs before the first spec even
    when that spec is a name (it used to be skipped then)."""
    edges = _plate()
    adapter = _adapter(edges, named={"Edge<1>"})

    result = features._add_fillet_impl(
        adapter, 1.0, ["Edge<1>", "0.02,0.0,0.006", "0.02,0.0,-0.006"]
    )

    assert result.is_success, result.error
    assert adapter.log.events == [
        "ClearSelection2",
        "ForceRebuild3:True",
        "SelectByID2:Edge<1>",
        "Select4:front-bottom",
        "Select4:back-bottom",
    ]


def test_named_specs_alone_neither_rebuild_nor_walk_the_body() -> None:
    adapter = _adapter(_plate(), named={"Edge<1>", "Edge<2>"})

    result = features._add_fillet_impl(adapter, 1.0, ["Edge<1>", "Edge<2>"])

    assert result.is_success, result.error
    assert adapter.log.calls["ForceRebuild3"] == 0
    assert adapter.log.calls["GetBodies2"] == 0


def test_the_first_spec_that_fails_names_the_error() -> None:
    """Specs are still selected in order: a bad name before an off-edge point
    is the one reported."""
    adapter = _adapter(_plate(), named=set())

    result = features._add_fillet_impl(
        adapter, 1.0, ["0.02,0.0,0.006", "Edge<bad>", "0.02,-0.002,0.006"]
    )

    assert result.is_error
    assert result.error == "Failed to select edge: Edge<bad>"


def test_chamfer_walks_the_body_once_for_all_its_points() -> None:
    """Each chamfer point used to build its own picker: a body walk (and a
    rebuild check) per point."""
    edges = _plate()
    adapter = _adapter(edges)
    specs = ["0.02,0.0,0.006", "0.04,0.01,0.006", "0.02,0.02,-0.006"]

    result = features._add_chamfer_impl(adapter, 1.0, specs)

    assert result.is_success, result.error
    assert result.data.name == "Chamfer1"
    calls = adapter.log.calls
    assert calls["GetBodies2"] == calls["GetEdges"] == calls["ForceRebuild3"] == 1
    assert [e.name for e in edges if e.selected_with] == [
        "front-bottom",
        "front-right",
        "back-top",
    ]


def test_chamfer_face_specs_select_the_face_with_box_reads() -> None:
    """Two face points make face boxes worth reading: GetBox once per face,
    and only the face under each point is measured."""
    log = _Log()
    front = _Face(log, "front", (0.0, 0.0, 0.006), (0.04, 0.02, 0.006))
    back = _Face(log, "back", (0.0, 0.0, -0.006), (0.04, 0.02, -0.006))
    top = _Face(log, "top", (0.0, 0.02, -0.006), (0.04, 0.02, 0.006))
    adapter = _adapter(faces=[front, back, top])

    result = features._add_chamfer_impl(
        adapter, 1.0, ["face:0.02,0.01,0.006", "face:0.02,0.01,-0.006"]
    )

    assert result.is_success, result.error
    assert adapter.log.events == [
        "ClearSelection2",
        "ForceRebuild3:True",
        "Select4:front",
        "Select4:back",
    ]
    calls = adapter.log.calls
    assert calls["GetBox"] == 3
    assert calls["GetClosestPointOn"] == 2


def test_fillet_face_specs_select_each_face_edges() -> None:
    log = _Log()
    edges = _plate(log)
    front = _Face(log, "front", (0.0, 0.0, 0.006), (0.04, 0.02, 0.006), edges[:4])
    back = _Face(log, "back", (0.0, 0.0, -0.006), (0.04, 0.02, -0.006), edges[4:8])
    front.box = None  # unreadable: measured for every point
    adapter = _adapter(edges, [front, back])

    result = features._add_fillet_impl(
        adapter, 1.0, ["face:0.02,0.01,0.006", "face:0.02,0.01,-0.006"]
    )

    assert result.is_success, result.error
    assert [e.selected_with[0][0] for e in edges[:8]] == [False] + [True] * 7
    calls = adapter.log.calls
    assert calls["GetBox"] == 2
    # front (no box) for both points, back for the second only.
    assert calls["GetClosestPointOn"] == 3


# ---- the picker's own pieces -----------------------------------------------------


def test_rebuild_runs_once_per_picker() -> None:
    adapter = _adapter(_plate())
    picker = features._BodyEntityPicker(adapter)

    picker.rebuild()
    picker.rebuild()
    assert features._select_edge_by_coord(
        adapter, 0.02, 0.0, 0.006, append=False, picker=picker
    )

    assert adapter.log.calls["ForceRebuild3"] == 1


def test_select_data_is_made_once_per_mark() -> None:
    edges = _plate()
    adapter = _adapter(edges)
    picker = features._BodyEntityPicker(adapter)

    assert picker.select(edges[0], False)
    assert picker.select(edges[1], True)
    assert picker.select(edges[2], True, mark=2)

    assert adapter.log.calls["CreateSelectData"] == 2
    plain, marked = edges[1].selected_with[0][1], edges[2].selected_with[0][1]
    assert edges[0].selected_with[0][1] is plain
    assert (plain.Mark, marked.Mark) == (0, 2)


def test_select_data_that_cannot_be_made_is_tried_again() -> None:
    edges = _plate()
    adapter = _adapter(edges)
    adapter.currentModel.manager.made = False
    picker = features._BodyEntityPicker(adapter)

    assert not picker.select(edges[0], False)
    adapter.currentModel.manager.made = True
    assert picker.select(edges[0], False)

    assert adapter.log.calls["CreateSelectData"] == 2


# ---- boxes ---------------------------------------------------------------------


def _inside(box: features._Box, p: Point) -> bool:
    lo, hi = box
    return all(a <= c <= b for a, b, c in zip(lo, hi, p, strict=True))


def test_a_line_box_spans_its_vertices_plus_the_pad() -> None:
    line = _Line(_Log(), "l", (0.04, 0.0, 0.006), (0.0, 0.02, 0.006))
    pad = features._BOX_PAD_M

    lo, hi = features._edge_box(_adapter(), line)

    assert lo == pytest.approx((-pad, -pad, 0.006 - pad))
    assert hi == pytest.approx((0.04 + pad, 0.02 + pad, 0.006 + pad))


@pytest.mark.parametrize(
    "arc",
    [
        _Arc(_Log(), "rim", (0.02, 0.01, 0.006), 0.004),
        _Arc(_Log(), "half", (0.0, 0.0, 0.0), 0.003, sweep=math.pi),
        _Arc(
            _Log(),
            "tilted",
            (0.01, -0.02, 0.03),
            0.005,
            axis=(1.0, 2.0, 3.0),
            ref=(2.0, -1.0, 0.0),
        ),
    ],
    ids=lambda a: a.name,
)
def test_a_circle_box_holds_every_point_of_the_circle(arc: _Arc) -> None:
    box = features._edge_box(_adapter(), arc)

    assert box is not None
    full = _Arc(_Log(), "full", arc.center, arc.radius, arc.n, arc.u)
    for step in range(360):
        assert _inside(box, full.point_at(math.radians(step)))


def test_a_flat_circle_box_is_flat() -> None:
    """A hole rim in z=6 mm gets a box only the pad thick in z, not r."""
    rim = _Arc(_Log(), "rim", (0.02, 0.01, 0.006), 0.004)

    lo, hi = features._edge_box(_adapter(), rim)

    assert hi[2] - lo[2] == pytest.approx(2 * features._BOX_PAD_M)
    assert hi[0] - lo[0] == pytest.approx(0.008 + 2 * features._BOX_PAD_M)


def test_a_circle_with_no_axis_gets_its_radius_every_way() -> None:
    lo, hi = features._circle_box([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -0.002])

    assert hi == pytest.approx((0.002 + features._BOX_PAD_M,) * 3)
    assert lo == pytest.approx((-0.002 - features._BOX_PAD_M,) * 3)


def _with(edge: _Edge, **changes: Any) -> _Edge:
    for name, value in changes.items():
        setattr(edge, name, value)
    return edge


@pytest.mark.parametrize(
    "edge",
    [
        _Other(_Log(), "spline", (0.0, 0.0, 0.0), (0.01, 0.0, 0.0)),
        _with(_Line(_Log(), "l", (0, 0, 0), (1, 0, 0)), GetCurve=lambda: None),
        _with(_Line(_Log(), "l", (0, 0, 0), (1, 0, 0)), ends=None),  # no vertices
        _with(_Line(_Log(), "l", (0, 0, 0), (1, 0, 0)), ends=((0, 0, 0), None)),
        _with(_Line(_Log(), "l", (0, 0, 0), (1, 0, 0)), ends=((0, 0), (1, 0, 0))),
        _with(_Arc(_Log(), "a", (0, 0, 0), 0.001), circle=None),
        _with(_Arc(_Log(), "a", (0, 0, 0), 0.001), circle=[0.0, 0.0, 0.0, 0.0]),
    ],
    ids=[
        "unknown-curve",
        "no-curve",
        "no-vertices",
        "no-end-point",
        "short-point",
        "no-circle-params",
        "short-circle-params",
    ],
)
def test_unreadable_edge_geometry_gives_no_box(edge: _Edge) -> None:
    assert features._edge_box(_adapter(), edge) is None


def test_a_face_box_orders_its_corners_and_pads_them() -> None:
    face = _Face(_Log(), "f", (0.0, 0.01, 0.006), (0.04, 0.02, 0.006))
    pad = features._BOX_PAD_M

    lo, hi = features._face_box(_adapter(), face)

    assert lo == pytest.approx((-pad, 0.01 - pad, 0.006 - pad))
    assert hi == pytest.approx((0.04 + pad, 0.02 + pad, 0.006 + pad))


@pytest.mark.parametrize("box", [None, [0.0, 0.0, 0.0, 1.0, 1.0]])
def test_an_unreadable_face_box_gives_none(box) -> None:
    face = _Face(_Log(), "f", (0.0, 0.0, 0.0), (1.0, 1.0, 0.0))
    face.box = box

    assert features._face_box(_adapter(), face) is None


@pytest.mark.parametrize(
    ("box", "point", "distance"),
    [
        (None, (5.0, 5.0, 5.0), 0.0),
        (((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), (0.5, 0.5, 0.5), 0.0),
        (((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), (4.0, -4.0, 0.5), math.hypot(3, 4)),
    ],
)
def test_box_distance(box, point, distance) -> None:
    assert features._box_distance(box, point) == pytest.approx(distance)
