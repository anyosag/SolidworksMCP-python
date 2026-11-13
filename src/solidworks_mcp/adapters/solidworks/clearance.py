"""The minimum distance between two components of an assembly (``measure_clearance``).

``check_interference`` reports only overlaps, so a 0.25 mm latch clearance
could be checked only "by construction" (Cellvis dish rack, 2026-11-12).
This module measures it face pair by face pair (change
``cellvis-assembly-and-print-checks``, D2).

The COM calls, as probe 1 ran them on SOLIDWORKS 2026 SP4.1
(``tests/scripts/probe_clearance.py``):

* ``IComponent2.GetBodies2(swSolidBody)``, each body's ``GetFaces()``, and
  each face's twin in the assembly, ``IComponent2.GetCorrespondingEntity``;
* ``IFace2.GetBox()``: six numbers in metres in the *part's* coordinates
  (the twin's box is the same), padded by about 0.15 mm on a plane. Turned
  into assembly coordinates by the component's ``Transform2``, it bounds the
  face from below: no point of the face is nearer than its box;
* ``IModelDoc2.ClosestDistance(twin_a, twin_b, p1, p2)``: the distance in
  metres, with the two nearest points in assembly coordinates through two
  byref VARIANTs. A cylinder is measured to its surface: a Ø9.5 pin in a Ø10
  hole read 0.25 mm, not the 0 its axis would give.

The pairs are measured nearest box first, and the search stops once the
next pair's box distance is above the best distance found: no face pair
after it can be nearer. A dish-rack latch, about 40 faces a side, then needs
tens of measurements instead of 1600.

A component lying wholly inside another, with no faces crossing, reads its
gap to the outer component's faces, not 0: ``check_interference`` finds
that overlap.

The pure pieces (transforms, box distances, the search) are separate from
the COM walk so they can be tested without SolidWorks.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .. import sw_type_info as _sw_type_info
from . import limits
from .com_utils import as_list
from .com_utils import attempt as _attempt
from .com_utils import flag as _flag

#: ``swBodyType_e.swSolidBody``.
SOLID_BODY = 0
#: ``swComponentSuppressionState_e``: suppressed, and the two lightweight
#: states, whose bodies aren't loaded.
SUPPRESSED = 0
LIGHTWEIGHT = frozenset({1, 4})
#: A distance at or under this (mm) is touching.
TOUCHING_MM = 1e-6

#: A box ``[x1, y1, z1, x2, y2, z2]``, low corner first.
Box = list[float]
Rows = Sequence[Sequence[float]]


class InvalidRequest(ValueError):
    """The components asked can't be measured as given (``invalid_input``).

    The message starts ``Invalid request:``, which the tool error classifier
    reads as ``invalid_input``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid request: {message}")


def transform_point(
    point: Sequence[float], rows: Rows, origin: Sequence[float]
) -> list[float]:
    """A component's point in the assembly: ``p . R + t``.

    Each row of ``R`` is one of the component's axes in assembly
    coordinates (``placement``, D1).
    """
    return [
        sum(float(point[k]) * float(rows[k][j]) for k in range(3)) + float(origin[j])
        for j in range(3)
    ]


def transform_box(box: Sequence[float], rows: Rows, origin: Sequence[float]) -> Box:
    """The assembly-axis box around a component's box once it is placed.

    The eight corners are transformed and boxed again, so the result holds
    every point the original box held: still a lower bound for a face in it.
    """
    lo = [min(float(box[a]), float(box[a + 3])) for a in range(3)]
    hi = [max(float(box[a]), float(box[a + 3])) for a in range(3)]
    corners = [
        transform_point(
            [hi[a] if (i >> a) & 1 else lo[a] for a in range(3)], rows, origin
        )
        for i in range(8)
    ]
    return [min(c[a] for c in corners) for a in range(3)] + [
        max(c[a] for c in corners) for a in range(3)
    ]


def box_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """The distance between two boxes; 0 when they touch or overlap."""
    gaps = [
        max(0.0, float(a[k]) - float(b[k + 3]), float(b[k]) - float(a[k + 3]))
        for k in range(3)
    ]
    return math.sqrt(sum(g * g for g in gaps))


def pair_order(
    boxes_a: Sequence[Sequence[float]], boxes_b: Sequence[Sequence[float]]
) -> list[tuple[float, int, int]]:
    """Every pair ``(box distance, i, j)``, nearest first."""
    return sorted(
        (box_distance(a, b), i, j)
        for i, a in enumerate(boxes_a)
        for j, b in enumerate(boxes_b)
    )


@dataclass(frozen=True)
class Nearest:
    """The nearest face pair found.

    Attributes:
        distance: Their distance, in the measuring call's units.
        pair: ``(i, j)``: the face of each side.
        point_a: The nearest point on face ``i``.
        point_b: The nearest point on face ``j``.
        pairs_checked: How many pairs were measured to find it.
    """

    distance: float
    pair: tuple[int, int]
    point_a: list[float]
    point_b: list[float]
    pairs_checked: int


#: ``measure(i, j)`` gives ``(distance, point_a, point_b)``, or None when the
#: pair couldn't be measured.
Measure = Callable[[int, int], tuple[float, list[float], list[float]] | None]


def nearest_pair(
    boxes_a: Sequence[Sequence[float]],
    boxes_b: Sequence[Sequence[float]],
    measure: Measure,
    touching: float = 0.0,
    check: Callable[[], None] = lambda: None,
) -> Nearest | None:
    """Measure the face pairs nearest box first, and stop when no pair can be nearer.

    The search stops at the first pair whose box distance is above the best
    distance measured, or once a pair is at ``touching`` or under: nothing is
    nearer than touching.

    Args:
        boxes_a: Each face's box on one side, in one frame.
        boxes_b: The same for the other side.
        measure: Measures one pair (see :data:`Measure`).
        touching: The distance that counts as touching.
        check: Called before each measurement (``limits.check``).

    Returns:
        Nearest | None: The nearest pair, or None when no pair was measured.
    """
    best: tuple[float, int, int, list[float], list[float]] | None = None
    checked = 0
    for bound, i, j in pair_order(boxes_a, boxes_b):
        if best is not None and (bound > best[0] or best[0] <= touching):
            break
        check()
        checked += 1
        got = measure(i, j)
        if got is not None and (best is None or got[0] < best[0]):
            best = (got[0], i, j, got[1], got[2])
    if best is None:
        return None
    return Nearest(best[0], (best[1], best[2]), best[3], best[4], checked)


# ---- COM -------------------------------------------------------------------


@dataclass
class _Face:
    """One face of a component: the part's face, its twin, and its box."""

    face: Any
    twin: Any
    box_m: Box


def _mm(values: Sequence[float], digits: int = 4) -> list[float]:
    return [round(float(v) * 1000.0, digits) + 0.0 for v in values]


def _placement(adapter: Any, component: Any, label: str) -> tuple[Rows, list[float]]:
    """The component's rotation rows and translation (m) from ``Transform2``.

    Raises:
        RuntimeError: The transform can't be read.
    """
    transform = _attempt(adapter, lambda: component.Transform2)
    data = _attempt(adapter, lambda: transform.ArrayData) if transform else None
    if not isinstance(data, (list, tuple)) or len(data) < 12:
        raise RuntimeError(f"The placement of {label} could not be read (Transform2).")
    values = [float(v) for v in data]
    return [values[0:3], values[3:6], values[6:9]], values[9:12]


def _solid_bodies(adapter: Any, component: Any, label: str) -> list[Any]:
    """The component's solid bodies; a suppressed or bodiless one is refused.

    Raises:
        InvalidRequest: Naming the component, why, and what to do.
    """
    _flag(adapter, component, "GetSuppression2", "GetBodies2")
    state = _attempt(adapter, lambda: component.GetSuppression2())
    if state == SUPPRESSED:
        raise InvalidRequest(
            f"{label} is suppressed, so there is nothing of it to measure; "
            "unsuppress it first."
        )
    bodies = as_list(_attempt(adapter, lambda: component.GetBodies2(SOLID_BODY)))
    if bodies:
        return bodies
    if state in LIGHTWEIGHT:
        raise InvalidRequest(
            f"{label} is lightweight, so its bodies aren't loaded; resolve it first."
        )
    raise InvalidRequest(
        f"{label} holds no solid body (a sketch-only or surface part), so "
        "there is nothing of it to measure."
    )


def component_faces(adapter: Any, component: Any, label: str) -> list[_Face]:
    """Every face of the component's solid bodies, with its twin and its box.

    The box is ``IFace2.GetBox`` (part coordinates) placed in the assembly by
    the component's transform. A face without a twin or a box is left out.

    Args:
        adapter: A connected adapter.
        component: The ``IComponent2``.
        label: How messages name it, e.g. ``component_b 'pin-1'``.

    Raises:
        InvalidRequest: The component is suppressed or holds no solid body.
        RuntimeError: Its placement, or no face, could be read in the assembly.
    """
    bodies = _solid_bodies(adapter, component, label)
    _flag(adapter, component, "GetCorrespondingEntity")
    rows, origin = _placement(adapter, component, label)
    faces: list[_Face] = []
    for body in bodies:
        _flag(adapter, body, "GetFaces")
        for face in as_list(_attempt(adapter, lambda b=body: b.GetFaces())):
            limits.check("reading faces for the clearance")
            _flag(adapter, face, "GetBox")
            box = _attempt(adapter, lambda f=face: f.GetBox())
            twin = _attempt(adapter, lambda f=face: component.GetCorrespondingEntity(f))
            if twin is None or not isinstance(box, (list, tuple)) or len(box) < 6:
                continue
            faces.append(_Face(face, twin, transform_box(box[:6], rows, origin)))
    if not faces:
        raise RuntimeError(
            f"No face of {label} could be read in the assembly "
            "(GetCorrespondingEntity or GetBox gave nothing)."
        )
    return faces


def _closest(adapter: Any, model: Any, a: Any, b: Any) -> Any:
    """``ClosestDistance`` between two assembly faces: ``(m, point_a, point_b)``.

    Returns:
        The distance in metres and the two points in assembly coordinates
        (metres), or None when SolidWorks gave no distance (a failed call
        returns -1).
    """
    from .io import _byref_variant

    p1, p2 = _byref_variant(), _byref_variant()
    distance = _attempt(adapter, lambda: model.ClosestDistance(a, b, p1, p2))
    if not isinstance(distance, (int, float)) or distance < 0:
        return None
    points = [as_list(getattr(p, "value", None)) for p in (p1, p2)]
    if any(len(p) < 3 for p in points):
        return None
    return (
        float(distance),
        [float(v) for v in points[0][:3]],
        [float(v) for v in points[1][:3]],
    )


def face_kind(adapter: Any, face: Any) -> str:
    """``plane``, ``cylinder`` or ``other``, from the face's surface."""
    _flag(adapter, face, "GetSurface")
    surface = _attempt(adapter, lambda: face.GetSurface())
    if surface is None:
        return "other"
    _flag(adapter, surface, "IsPlane", "IsCylinder")
    if _attempt(adapter, lambda: surface.IsPlane(), False):
        return "plane"
    if _attempt(adapter, lambda: surface.IsCylinder(), False):
        return "cylinder"
    return "other"


def measure_clearance(
    adapter: Any, component_a: str, component_b: str
) -> dict[str, Any]:
    """The minimum distance between two top-level components of the active assembly.

    Args:
        adapter: A connected adapter with an assembly as ``currentModel``.
        component_a: An instance name, as ``list_components`` reports it.
        component_b: Another one.

    Returns:
        dict[str, Any]: ``component_a``, ``component_b``, ``clearance_mm``,
        ``touching``, ``point_a_mm`` and ``point_b_mm`` (assembly
        coordinates), ``face_a`` and ``face_b`` (``kind`` and ``box_mm``, in
        assembly coordinates), ``pairs_checked`` and ``pairs_total``.

    Raises:
        InvalidRequest: The same component twice, or one that is suppressed
            or holds no solid body (a lightweight one, unloaded).
        Exception: A component that isn't in the assembly (the message
            lists what it holds).
        RuntimeError: Nothing could be measured.
    """
    from .io import _find_components

    if component_a == component_b:
        raise InvalidRequest(
            f"component_a and component_b are both {component_a!r}; give two "
            "different components."
        )
    model = adapter.currentModel
    assembly = _sw_type_info.flagged(model, "IAssemblyDoc")
    found = _find_components(adapter, assembly, [component_a, component_b])
    sides = []
    for role, name in (("component_a", component_a), ("component_b", component_b)):
        sides.append(component_faces(adapter, found[name], f"{role} {name!r}"))
    faces_a, faces_b = sides

    _flag(adapter, model, "ClosestDistance")
    nearest = nearest_pair(
        [f.box_m for f in faces_a],
        [f.box_m for f in faces_b],
        lambda i, j: _closest(adapter, model, faces_a[i].twin, faces_b[j].twin),
        touching=TOUCHING_MM / 1000.0,
        check=lambda: limits.check("measuring clearance"),
    )
    if nearest is None:
        raise RuntimeError(
            f"ClosestDistance measured none of the {len(faces_a) * len(faces_b)} "
            f"face pairs of {component_a} and {component_b}."
        )
    clearance_mm = nearest.distance * 1000.0
    touching = clearance_mm <= TOUCHING_MM
    i, j = nearest.pair
    return {
        "component_a": component_a,
        "component_b": component_b,
        "clearance_mm": 0.0 if touching else round(clearance_mm, 6),
        "touching": touching,
        "point_a_mm": _mm(nearest.point_a),
        "point_b_mm": _mm(nearest.point_b),
        "face_a": {
            "kind": face_kind(adapter, faces_a[i].face),
            "box_mm": _mm(faces_a[i].box_m),
        },
        "face_b": {
            "kind": face_kind(adapter, faces_b[j].face),
            "box_mm": _mm(faces_b[j].box_m),
        },
        "pairs_checked": nearest.pairs_checked,
        "pairs_total": len(faces_a) * len(faces_b),
    }
