"""Select edges by rule: from a feature, a face or the whole part, then filtered.

``select_face_edges`` takes every edge of one face. Modelling a part with a
hundred edges needs more: "the edges the cut made", "the straight edges
along Y", "the edges inside this box". This module answers those in two
pieces:

* **Pure rules** (no COM), shared by the live and mock adapters:
  :func:`validate_edge_query` and :func:`filter_edges`, which work on the
  edge descriptions :func:`face_selection.describe_edge` returns (mm).
* **COM gathering** (:class:`EdgeRuleSelector`): the candidate edges for a
  source - a feature's faces (``IFeature.GetFaces``), one face, or every
  body's edges (``IBody2.GetEdges``) - de-duplicated, because an edge
  shared by two of a feature's faces is returned by both.

The selection itself is :meth:`FaceEdgeSelector.select`: all or nothing.
"""

from __future__ import annotations

import math
from typing import Any

from .com_utils import as_list
from .com_utils import attempt as _attempt
from .com_utils import flag as _flag
from .face_selection import EDGE_TYPES, FaceEdgeSelector, describe_edge, side_vector

#: The sources an edge query may name; none of them means every edge.
EDGE_SOURCES = ("feature", "face_point", "side", "plane")

#: Axis names ``parallel_to`` accepts.
AXIS_VECTORS: dict[str, tuple[float, float, float]] = {
    "x": (1.0, 0.0, 0.0),
    "y": (0.0, 1.0, 0.0),
    "z": (0.0, 0.0, 1.0),
}

#: The most edge descriptions a reply lists; the count is always exact.
MAX_DESCRIBED_EDGES = 50

#: How far an edge may stick out of ``inside_box`` and still be inside, mm.
_BOX_TOLERANCE_MM = 1e-3


def axis_vector(value: str | list[float]) -> tuple[float, float, float]:
    """The unit vector for ``"x"``/``"y"``/``"z"`` or an ``[x, y, z]`` direction.

    Raises:
        ValueError: For another name, a vector that isn't three numbers, or
            a zero vector.
    """
    if isinstance(value, str):
        try:
            return AXIS_VECTORS[value.strip().lower()]
        except KeyError:
            raise ValueError(
                f"parallel_to must be 'x', 'y', 'z' or [x, y, z], not {value!r}"
            ) from None
    if len(value) != 3:
        raise ValueError("parallel_to as a direction must be [x, y, z]")
    length = math.sqrt(sum(float(c) ** 2 for c in value))
    if length < 1e-12:
        raise ValueError("parallel_to must not be the zero vector")
    x, y, z = (float(c) / length for c in value)
    return (x, y, z)


def validate_edge_query(query: dict[str, Any]) -> str | None:
    """Check an edge query; return what is wrong with it, or None.

    Args:
        query: ``feature``, ``face_point``, ``side`` or ``plane`` (at most
            one; none means every edge), plus the filters ``edge_type``,
            ``parallel_to``, ``inside_box``, ``min_length`` and
            ``max_length`` (mm), and ``parallel_tolerance_deg``.

    Returns:
        str | None: The problem, in words an agent can act on.
    """
    sources = [s for s in EDGE_SOURCES if query.get(s) not in (None, "")]
    if len(sources) > 1:
        return (
            "Give at most one of feature, face_point, side or plane "
            f"(got {', '.join(sources)})."
        )
    point = query.get("face_point")
    if point is not None and len(point) != 3:
        return "face_point must be [x, y, z] in millimetres."
    side = query.get("side")
    if side not in (None, ""):
        try:
            side_vector(str(side))
        except ValueError as exc:
            return str(exc)
    edge_type = query.get("edge_type", "all")
    if edge_type not in EDGE_TYPES:
        return f"edge_type must be one of {', '.join(EDGE_TYPES)} (got {edge_type!r})."
    if query.get("parallel_to") is not None:
        try:
            axis_vector(query["parallel_to"])
        except ValueError as exc:
            return str(exc)
    box = query.get("inside_box")
    if box is not None:
        if len(box) != 2 or any(len(corner) != 3 for corner in box):
            return "inside_box must be [[xmin, ymin, zmin], [xmax, ymax, zmax]] in mm."
        if any(lo > hi for lo, hi in zip(box[0], box[1], strict=True)):
            return "inside_box's first corner must be its minimum on every axis."
    low, high = query.get("min_length"), query.get("max_length")
    if low is not None and high is not None and low > high:
        return "min_length must not be more than max_length."
    return None


def edge_direction(info: dict[str, Any]) -> tuple[float, float, float] | None:
    """A straight edge's unit direction from its end points, or None."""
    start, end = info.get("start_mm"), info.get("end_mm")
    if info.get("curve") != "linear" or not start or not end:
        return None
    delta = [b - a for a, b in zip(start, end, strict=True)]
    length = math.sqrt(sum(c * c for c in delta))
    if length < 1e-12:
        return None
    x, y, z = (c / length for c in delta)
    return (x, y, z)


def edge_length(info: dict[str, Any]) -> float | None:
    """An edge's length in mm: end to end, or a full circle's circumference."""
    if info.get("length_mm") is not None:
        return float(info["length_mm"])
    if info.get("curve") == "circular" and info.get("radius_mm") is not None:
        return 2 * math.pi * float(info["radius_mm"])
    return None


def edge_extent(info: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    """The smallest box holding an edge's known points, mm, or None.

    A circular edge's box is its whole circle's (centre plus radius across
    the circle's plane), which holds any arc of it; a straight edge's is its
    two ends.
    """
    points = [p for p in (info.get("start_mm"), info.get("end_mm")) if p]
    center, radius, axis = (
        info.get("center_mm"),
        info.get("radius_mm"),
        info.get("axis"),
    )
    if center is not None and radius is not None and axis is not None:
        reach = [float(radius) * math.sqrt(max(0.0, 1.0 - float(a) ** 2)) for a in axis]
        points.append([c - r for c, r in zip(center, reach, strict=True)])
        points.append([c + r for c, r in zip(center, reach, strict=True)])
    if not points:
        return None
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    return low, high


def _is_parallel(
    info: dict[str, Any], axis: tuple[float, float, float], tolerance_deg: float
) -> bool:
    direction = edge_direction(info)
    if direction is None:
        return False
    cosine = abs(sum(a * b for a, b in zip(direction, axis, strict=True)))
    return cosine >= math.cos(math.radians(tolerance_deg))


def _is_inside(info: dict[str, Any], box: list[list[float]]) -> bool:
    extent = edge_extent(info)
    if extent is None:
        return False
    low, high = extent
    return all(
        low[i] >= box[0][i] - _BOX_TOLERANCE_MM
        and high[i] <= box[1][i] + _BOX_TOLERANCE_MM
        for i in range(3)
    )


def _length_ok(info: dict[str, Any], low: float | None, high: float | None) -> bool:
    length = edge_length(info)
    if length is None:
        return False
    return (low is None or length >= low - 1e-6) and (
        high is None or length <= high + 1e-6
    )


def filter_edges(
    edges: list[tuple[Any, dict[str, Any]]], query: dict[str, Any]
) -> tuple[list[tuple[Any, dict[str, Any]]], dict[str, int]]:
    """Keep the edges every rule in ``query`` allows.

    Args:
        edges: ``(handle, description)`` pairs, descriptions in mm.
        query: A query :func:`validate_edge_query` accepted.

    Returns:
        tuple: The kept pairs, and how many were left after each rule that
        was given (``candidates`` first), so an empty result says which rule
        removed them.
    """
    counts = {"candidates": len(edges)}
    kept = edges
    edge_type = query.get("edge_type", "all")
    if edge_type != "all":
        kept = [e for e in kept if e[1].get("curve") == edge_type]
        counts["edge_type"] = len(kept)
    if query.get("parallel_to") is not None:
        axis = axis_vector(query["parallel_to"])
        tolerance = float(query.get("parallel_tolerance_deg") or 1.0)
        kept = [e for e in kept if _is_parallel(e[1], axis, tolerance)]
        counts["parallel_to"] = len(kept)
    if query.get("inside_box") is not None:
        kept = [e for e in kept if _is_inside(e[1], query["inside_box"])]
        counts["inside_box"] = len(kept)
    low, high = query.get("min_length"), query.get("max_length")
    if low is not None or high is not None:
        kept = [e for e in kept if _length_ok(e[1], low, high)]
        counts["length"] = len(kept)
    return kept, counts


def describe_source(query: dict[str, Any]) -> str:
    """The source in words, for messages: ``"feature 'Cut-Extrude2'"`` etc."""
    if query.get("feature"):
        return f"feature {query['feature']!r}"
    if query.get("face_point") is not None:
        return f"the face at {list(query['face_point'])} mm"
    if query.get("side"):
        return f"the {query['side']} face"
    if query.get("plane"):
        return f"the face(s) on {query['plane']!r}"
    return "the part"


def no_match_message(query: dict[str, Any], counts: dict[str, int]) -> str:
    """Why nothing matched: the source's edge count, then each rule's."""
    steps = [f"{describe_source(query)} has {counts['candidates']} edge(s)"]
    steps += [f"{counts[rule]} pass {rule}" for rule in counts if rule != "candidates"]
    return "No matching edges found: " + "; ".join(steps) + "."


def edge_key(info: dict[str, Any]) -> tuple[Any, ...] | None:
    """A key equal for the same edge reached through two of its faces.

    No two edges of a body share their curve type, end points and circle,
    so the geometry (rounded to 1 nm) identifies the edge. An edge with
    neither end points nor a circle (a closed spline) has no key: None,
    and is never merged with another.
    """

    def _rounded(point: list[float] | None) -> tuple[float, ...] | None:
        return None if point is None else tuple(round(float(c), 6) for c in point)

    ends = sorted(
        (
            p
            for p in (_rounded(info.get("start_mm")), _rounded(info.get("end_mm")))
            if p
        ),
    )
    if not ends and info.get("center_mm") is None:
        return None
    return (
        info.get("curve"),
        tuple(ends),
        _rounded(info.get("center_mm")),
        None if info.get("radius_mm") is None else round(float(info["radius_mm"]), 6),
    )


class EdgeRuleSelector:
    """Gather the candidate edges for an edge query on the active part.

    Args:
        adapter: A connected ``PyWin32Adapter``.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._faces = FaceEdgeSelector(adapter)

    def candidates(self, query: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
        """The source's edges, each once, with their descriptions.

        Raises:
            LookupError: The feature, face or plane isn't there, or the part
                has no edges.
        """
        if query.get("feature"):
            faces = self._feature_faces(str(query["feature"]))
            return self._unique(edge for face in faces for edge in self._edges_of(face))
        if any(query.get(s) not in (None, "") for s in ("face_point", "side", "plane")):
            faces = self._faces.resolve(
                query.get("face_point"), query.get("side"), query.get("plane")
            )
            return self._unique(
                edge for face in faces for edge in self._edges_of(face.handle)
            )
        edges = self._unique(self._body_edges())
        if not edges:
            raise LookupError("The active part has no solid body edges.")
        return edges

    def _feature_faces(self, name: str) -> list[Any]:
        model = self._adapter.currentModel
        feature = _attempt(self._adapter, lambda: model.FeatureByName(name))
        if feature is None:
            raise LookupError(
                f"Feature {name!r} not found; list_features names the features."
            )
        _flag(self._adapter, feature, "GetFaces")
        faces = as_list(_attempt(self._adapter, lambda: feature.GetFaces()))
        if not faces:
            raise LookupError(
                f"Feature {name!r} has no faces in the body (a sketch, plane or "
                "suppressed feature has none)."
            )
        return faces

    def _edges_of(self, face: Any) -> list[Any]:
        _flag(self._adapter, face, "GetEdges")
        return as_list(_attempt(self._adapter, lambda: face.GetEdges()))

    def _body_edges(self) -> list[Any]:
        model = self._adapter.currentModel
        _flag(self._adapter, model, "GetBodies2")
        edges: list[Any] = []
        for body in as_list(
            _attempt(self._adapter, lambda: model.GetBodies2(0, False))
        ):
            _flag(self._adapter, body, "GetEdges")
            edges += as_list(_attempt(self._adapter, lambda b=body: b.GetEdges()))
        return edges

    def _unique(self, edges: Any) -> list[tuple[Any, dict[str, Any]]]:
        seen: set[tuple[Any, ...]] = set()
        out = []
        for edge in edges:
            info = describe_edge(self._adapter, edge)
            key = edge_key(info)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            out.append((edge, info))
        return out

    def select(
        self, edges: list[tuple[Any, dict[str, Any]]], append: bool
    ) -> int | None:
        """Select every edge, all or nothing (see ``FaceEdgeSelector.select``)."""
        return self._faces.select(edges, append)
