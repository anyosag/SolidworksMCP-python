"""The minimum distance between two components (``clearance``).

The fake assembly holds blocks made of six flat faces each. ``GetBox`` pads
every face by 0.15 mm, as SolidWorks pads a plane, so the boxes are only a
lower bound, and the fake ``ClosestDistance`` measures the exact faces in
assembly coordinates, the way probe 1 found SolidWorks does.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import clearance as cl
from solidworks_mcp.adapters.solidworks import io as io_module
from solidworks_mcp.adapters.solidworks import limits

_IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
#: A quarter turn about Y: the component's X axis points along -Z.
_QUARTER_Y = [[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]
_PAD_M = 0.00015


@pytest.fixture(autouse=True)
def _plain_com(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake objects need no method flagging or dispatch wrapping."""
    monkeypatch.setattr(cl, "_sw_type_info", SimpleNamespace(flagged=lambda o, *_: o))
    monkeypatch.setattr(io_module, "_as_com", lambda _adapter, obj, _iface: obj)


# ---- pure pieces ---------------------------------------------------------------


def test_a_point_turns_by_the_rows_then_moves() -> None:
    assert cl.transform_point([1, 2, 3], _IDENTITY, [10, 0, 0]) == [11, 2, 3]
    # X goes to -Z, Z to +X.
    assert cl.transform_point([1, 0, 0], _QUARTER_Y, [0, 0, 0]) == [0, 0, -1]
    assert cl.transform_point([0, 0, 1], _QUARTER_Y, [0, 0, 0]) == [1, 0, 0]


def test_a_box_is_boxed_again_after_a_turn() -> None:
    """The probe's 20 x 6 x 10 block, turned about Y and moved to x = 100."""
    box = [0, 0, -10, 20, 6, 0]

    assert cl.transform_box(box, _QUARTER_Y, [100, 0, 0]) == [90, 0, -20, 100, 6, 0]
    # Corners may come in any order.
    assert cl.transform_box([20, 6, 0, 0, 0, -10], _IDENTITY, [0, 0, 0]) == [
        0,
        0,
        -10,
        20,
        6,
        0,
    ]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ([0, 0, 0, 1, 1, 1], [3, 0, 0, 4, 1, 1], 2.0),
        ([0, 0, 0, 1, 1, 1], [4, 5, 0, 5, 6, 1], 5.0),  # 3-4-5 corner to corner
        ([0, 0, 0, 2, 2, 2], [1, 1, 1, 3, 3, 3], 0.0),  # overlap
        ([0, 0, 0, 1, 1, 1], [1, 0, 0, 2, 1, 1], 0.0),  # touching
        ([3, 0, 0, 4, 1, 1], [0, 0, 0, 1, 1, 1], 2.0),  # either order
    ],
)
def test_box_distance(a: list[float], b: list[float], expected: float) -> None:
    assert cl.box_distance(a, b) == pytest.approx(expected)


def test_pairs_come_nearest_first() -> None:
    boxes_a = [[0, 0, 0, 1, 1, 1], [10, 0, 0, 11, 1, 1]]
    boxes_b = [[2, 0, 0, 3, 1, 1], [20, 0, 0, 21, 1, 1]]

    # Box distances 1, 7, 9 and 19.
    assert [(i, j) for _d, i, j in cl.pair_order(boxes_a, boxes_b)] == [
        (0, 0),
        (1, 0),
        (1, 1),
        (0, 1),
    ]


def test_the_search_stops_once_no_pair_can_be_nearer() -> None:
    boxes_a = [[0, 0, 0, 1, 1, 1]]
    boxes_b = [[2, 0, 0, 3, 1, 1], [5, 0, 0, 6, 1, 1], [9, 0, 0, 10, 1, 1]]
    measured: list[tuple[int, int]] = []

    def measure(i: int, j: int) -> tuple[float, list[float], list[float]]:
        measured.append((i, j))
        # The true distance is a little more than the box distance.
        return cl.box_distance(boxes_a[i], boxes_b[j]) + 0.5, [i], [j]

    nearest = cl.nearest_pair(boxes_a, boxes_b, measure)

    assert nearest is not None
    assert (nearest.distance, nearest.pair) == (1.5, (0, 0))
    # 1.5 beats the next bound (4), so only the first pair is measured.
    assert measured == [(0, 0)] and nearest.pairs_checked == 1
    assert (nearest.point_a, nearest.point_b) == ([0], [0])


def test_a_pair_nearer_than_its_box_order_is_still_found() -> None:
    boxes_a = [[0, 0, 0, 1, 1, 1]]
    boxes_b = [[1.5, 0, 0, 3, 1, 1], [2, 0, 0, 3, 1, 1]]
    true = {(0, 0): 3.0, (0, 1): 1.2}

    nearest = cl.nearest_pair(boxes_a, boxes_b, lambda i, j: (true[(i, j)], [], []))

    assert nearest is not None
    assert nearest.pair == (0, 1) and nearest.pairs_checked == 2


def test_a_touching_pair_ends_the_search() -> None:
    boxes = [[0, 0, 0, 1, 1, 1]] * 3
    calls: list[int] = []

    def measure(i: int, j: int) -> tuple[float, list[float], list[float]]:
        calls.append(j)
        return 0.0, [], []

    nearest = cl.nearest_pair(boxes[:1], boxes, measure, touching=1e-9)

    assert nearest is not None and nearest.distance == 0.0
    assert calls == [0]


def test_pairs_that_cannot_be_measured_are_passed_over() -> None:
    boxes_a = [[0, 0, 0, 1, 1, 1]]
    boxes_b = [[2, 0, 0, 3, 1, 1], [4, 0, 0, 5, 1, 1]]
    checks: list[str] = []

    nearest = cl.nearest_pair(
        boxes_a,
        boxes_b,
        lambda i, j: None if j == 0 else (3.0, [], []),
        check=lambda: checks.append("check"),
    )

    assert nearest is not None and nearest.pair == (0, 1)
    assert checks == ["check", "check"]
    assert cl.nearest_pair(boxes_a, boxes_b, lambda i, j: None) is None


# ---- the COM walk, on fakes ----------------------------------------------------


def _faces_of(block_mm: list[float]) -> list[list[float]]:
    """The six faces of a block as flat boxes, metres."""
    lo, hi = [v / 1000 for v in block_mm[:3]], [v / 1000 for v in block_mm[3:]]
    faces = []
    for axis in range(3):
        for level in (lo[axis], hi[axis]):
            face_lo, face_hi = list(lo), list(hi)
            face_lo[axis] = face_hi[axis] = level
            faces.append(face_lo + face_hi)
    return faces


class _Surface:
    def __init__(self, kind: str) -> None:
        self._kind = kind

    def IsPlane(self) -> bool:  # noqa: N802
        return self._kind == "plane"

    def IsCylinder(self) -> bool:  # noqa: N802
        return self._kind == "cylinder"


class _Face:
    """A part face: its exact box (m, part coordinates) and its padded GetBox."""

    def __init__(self, box_m: list[float], kind: str = "plane") -> None:
        self.box_m, self._kind = box_m, kind

    def GetBox(self) -> tuple[float, ...]:  # noqa: N802
        return tuple(
            [v - _PAD_M for v in self.box_m[:3]] + [v + _PAD_M for v in self.box_m[3:]]
        )

    def GetSurface(self) -> Any:  # noqa: N802
        return None if self._kind == "none" else _Surface(self._kind)


class _Twin:
    """The face in the assembly: its exact box placed by the component."""

    def __init__(self, face: _Face, component: _Component) -> None:
        self.box_m = cl.transform_box(face.box_m, component.rows, component.origin_m)


class _Component:
    def __init__(
        self,
        name: str,
        block_mm: list[float] | None,
        origin_mm: list[float] = (0.0, 0.0, 0.0),  # type: ignore[assignment]
        rows: list[list[float]] = _IDENTITY,
        suppression: int = 2,
        kind: str = "plane",
    ) -> None:
        self.Name2, self.rows, self.suppression = name, rows, suppression
        self.origin_m = [v / 1000 for v in origin_mm]
        self.faces = (
            [] if block_mm is None else [_Face(f, kind) for f in _faces_of(block_mm)]
        )
        flat = [x for row in rows for x in row]
        self.Transform2 = SimpleNamespace(
            ArrayData=(*flat, *self.origin_m, 1.0, 0.0, 0.0, 0.0)
        )

    def GetSuppression2(self) -> int:  # noqa: N802
        return self.suppression

    def GetBodies2(self, kind: int) -> Any:  # noqa: N802
        assert kind == cl.SOLID_BODY
        if not self.faces:
            return None
        return [SimpleNamespace(GetFaces=lambda: self.faces)]

    def GetCorrespondingEntity(self, face: _Face) -> _Twin:  # noqa: N802
        return _Twin(face, self)


def _nearest_points(a: list[float], b: list[float]) -> tuple[list[float], ...]:
    pa, pb = [], []
    for k in range(3):
        if a[k + 3] < b[k]:
            pa.append(a[k + 3])
            pb.append(b[k])
        elif b[k + 3] < a[k]:
            pa.append(a[k])
            pb.append(b[k + 3])
        else:
            middle = (max(a[k], b[k]) + min(a[k + 3], b[k + 3])) / 2
            pa.append(middle)
            pb.append(middle)
    return pa, pb


class _Model:
    def __init__(self, *components: _Component, fails: bool = False) -> None:
        self.components, self.fails = list(components), fails
        self.measured = 0

    def GetComponents(self, _top_level: bool) -> list[_Component]:  # noqa: N802
        return self.components

    def ClosestDistance(self, a: _Twin, b: _Twin, p1: Any, p2: Any) -> float:  # noqa: N802
        self.measured += 1
        if self.fails:
            return -1.0
        pa, pb = _nearest_points(a.box_m, b.box_m)
        p1.value, p2.value = tuple(pa), tuple(pb)
        return math.dist(pa, pb)


class _Adapter:
    def __init__(self, model: _Model) -> None:
        self.currentModel = model

    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001 - mirror the real adapter
            return default


def _latch() -> _Model:
    """A 10 mm block, and another 0.25 mm beyond it in X."""
    return _Model(
        _Component("tongue-1", [0, 0, 0, 10, 10, 10]),
        _Component("slot-1", [0, 0, 0, 10, 10, 10], origin_mm=[10.25, 0, 0]),
    )


def test_two_blocks_a_quarter_millimetre_apart() -> None:
    model = _latch()

    reply = cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")

    assert reply["clearance_mm"] == pytest.approx(0.25, abs=1e-6)
    assert reply["touching"] is False
    assert reply["point_a_mm"][0] == 10.0 and reply["point_b_mm"][0] == 10.25
    assert reply["face_a"] == {
        "kind": "plane",
        "box_mm": [9.85, -0.15, -0.15, 10.15, 10.15, 10.15],
    }
    assert reply["face_b"]["box_mm"][0] == pytest.approx(10.1)
    # The facing pair first; the stop rule leaves most of the 36 unmeasured.
    assert reply["pairs_total"] == 36
    assert reply["pairs_checked"] == model.measured
    assert reply["pairs_checked"] < 36
    assert (reply["component_a"], reply["component_b"]) == ("tongue-1", "slot-1")


def test_a_turned_component_is_measured_where_it_is() -> None:
    """A 20 x 6 x 10 block turned about Y lands at x 90..100; the gap is 5 mm."""
    model = _Model(
        _Component("plate-1", [0, 0, -20, 85, 6, 0]),
        _Component("block-1", [0, 0, -10, 20, 6, 0], [100, 0, 0], _QUARTER_Y),
    )

    reply = cl.measure_clearance(_Adapter(model), "plate-1", "block-1")

    assert reply["clearance_mm"] == pytest.approx(5.0)
    assert reply["point_b_mm"][0] == pytest.approx(90.0)


def test_overlapping_components_read_zero_and_touching() -> None:
    model = _Model(
        _Component("a-1", [0, 0, 0, 10, 10, 10]),
        _Component("b-1", [0, 0, 0, 10, 10, 10], origin_mm=[9, 0, 0]),
    )

    reply = cl.measure_clearance(_Adapter(model), "a-1", "b-1")

    assert reply["clearance_mm"] == 0.0 and reply["touching"] is True


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("cylinder", "cylinder"), ("other", "other"), ("none", "other")],
)
def test_the_face_kind_comes_from_its_surface(kind: str, expected: str) -> None:
    model = _Model(
        _Component("pin-1", [0, 0, 0, 10, 10, 10], kind=kind),
        _Component("hole-1", [0, 0, 0, 10, 10, 10], origin_mm=[12, 0, 0]),
    )

    reply = cl.measure_clearance(_Adapter(model), "pin-1", "hole-1")

    assert reply["face_a"]["kind"] == expected
    assert reply["face_b"]["kind"] == "plane"


def test_the_same_component_twice_is_an_invalid_request() -> None:
    with pytest.raises(cl.InvalidRequest, match="are both 'tongue-1'"):
        cl.measure_clearance(_Adapter(_latch()), "tongue-1", "tongue-1")


def test_an_unknown_component_lists_the_assembly() -> None:
    with pytest.raises(Exception, match="not found: pin-1") as caught:
        cl.measure_clearance(_Adapter(_latch()), "tongue-1", "pin-1")
    assert "tongue-1, slot-1" in str(caught.value)


@pytest.mark.parametrize(
    ("suppression", "block", "fragment"),
    [
        (0, [0, 0, 0, 1, 1, 1], "component_b 'slot-1' is suppressed"),
        (1, None, "component_b 'slot-1' is lightweight"),
        (2, None, "component_b 'slot-1' holds no solid body"),
    ],
)
def test_a_component_with_nothing_to_measure_is_named(
    suppression: int, block: list[float] | None, fragment: str
) -> None:
    model = _Model(
        _Component("tongue-1", [0, 0, 0, 10, 10, 10]),
        _Component("slot-1", block, suppression=suppression),
    )

    with pytest.raises(cl.InvalidRequest) as caught:
        cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")
    assert str(caught.value).startswith("Invalid request: ")
    assert fragment in str(caught.value)


def test_an_unreadable_placement_says_so() -> None:
    model = _latch()
    model.components[0].Transform2 = None

    with pytest.raises(RuntimeError, match="placement of component_a 'tongue-1'"):
        cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")


def test_faces_without_a_twin_or_a_box_are_left_out() -> None:
    model = _latch()
    component = model.components[1]
    component.GetCorrespondingEntity = lambda _face: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="No face of component_b 'slot-1'"):
        cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")

    model = _latch()
    model.components[0].faces[0].GetBox = lambda: None  # type: ignore[method-assign]
    reply = cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")
    assert reply["pairs_total"] == 30


def test_nothing_measured_is_an_error() -> None:
    model = _Model(*_latch().components, fails=True)

    with pytest.raises(RuntimeError, match="measured none of the 36 face pairs"):
        cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")


def test_a_distance_without_its_points_is_not_used() -> None:
    model = _latch()
    model.ClosestDistance = lambda *_args: 0.001  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="measured none"):
        cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")


def test_reading_faces_stops_when_the_client_has_gone() -> None:
    limits.mark_client_gone("test")

    with pytest.raises(limits.OperationStopped, match="reading faces"):
        cl.measure_clearance(_Adapter(_latch()), "tongue-1", "slot-1")


def test_limits_are_checked_between_measurements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _latch()
    checked: list[str] = []

    def check(doing: str) -> None:
        checked.append(doing)
        if doing == "measuring clearance" and model.measured == 2:
            raise limits.OperationStopped(f"Stopped {doing}")

    monkeypatch.setattr(cl, "limits", SimpleNamespace(check=check))

    with pytest.raises(limits.OperationStopped, match="Stopped measuring"):
        cl.measure_clearance(_Adapter(model), "tongue-1", "slot-1")
    assert model.measured == 2
    assert checked.count("reading faces for the clearance") == 12
