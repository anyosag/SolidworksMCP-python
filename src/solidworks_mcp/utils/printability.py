"""Check a part's mesh for printing in one orientation (``check_printability``).

Resin and FDM printers build a part layer by layer away from the build plate.
A surface facing the plate at a shallow angle needs supports; a region that
starts in mid-air (an island) needs them most; a flat overhang held at both
ends (a bridge) prints only over a short span; and a cavity that opens toward
the plate traps resin and pulls on each layer (a suction cup). This module
finds those on the part's STL mesh, with numpy and no COM. See the change
``cellvis-assembly-and-print-checks``, design D4.

Let ``d`` be the build direction (unit), a vertex's height ``h = v . d`` and
``h0`` the lowest height: the plate.

* **Plate faces**, every vertex within :data:`PLATE_MM` of ``h0``, are left
  out.
* **Down-facing**: ``n . d < 0``. Its angle from horizontal is
  ``acos(-n . d)``: 0 for a ceiling, 90 for a wall.
* **Regions**: down-facing triangles under the support angle, joined by
  shared edges. A boundary edge is *supported* when the triangle across it
  goes down (its third vertex is lower than the edge): a wall under it.
* **Islands**: a region with no supported edge, or a vertex lower than all its
  neighbours, above the plate.
* **Bridges**: a flat region (under :data:`FLAT_DEG`) supported along two or
  more separate runs of edges. Its span is twice the largest distance from a
  triangle's centre to the nearest support, across the build direction.
* **Suction cups**: a region (a ceiling) from under whose centre rays across
  the build direction hit the part all four ways, and a ray toward the plate
  hits nothing: the cavity opens onto the plate.

These are geometric checks on a mesh, not a slicer.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

#: Faces within this distance of the lowest height lie on the plate, mm.
PLATE_MM = 0.01

#: A region within this many degrees of horizontal is flat (a bridge or not).
FLAT_DEG = 10.0

#: The angle bands, degrees from horizontal, that down-facing area is split in.
BANDS = ((0.0, 15.0), (15.0, 30.0), (30.0, 45.0), (45.0, 60.0), (60.0, 90.0))

#: Vertices this close (mm) are one vertex.
_WELD_MM = 1e-3

#: Heights closer than this (mm) are level.
_LEVEL_MM = 1e-4

#: The most entries each list gives; the count is always exact.
MAX_LISTED = 50

_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def direction_vector(value: str | Sequence[float]) -> np.ndarray:
    """The unit build direction for ``"x"``, ``"-z"`` and the like, or a vector.

    Raises:
        ValueError: An unknown name, a vector that isn't three numbers, or the
            zero vector.
    """
    if isinstance(value, str):
        name = value.strip().lower()
        sign = -1.0 if name.startswith("-") else 1.0
        axis = _AXES.get(name.lstrip("+-"))
        if axis is None:
            raise ValueError(
                f"build_direction must be x, y, z, -x, -y, -z or [x, y, z], not {value!r}"
            )
        return np.array(axis) * sign
    vector = np.asarray(list(value), dtype=float)
    if vector.shape != (3,):
        raise ValueError("build_direction as a vector must be [x, y, z]")
    length = float(np.linalg.norm(vector))
    if length < 1e-12:
        raise ValueError("build_direction must not be the zero vector")
    return vector / length


def _weld(triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Shared vertices and faces from per-triangle corners; drops slivers."""
    corners = triangles.reshape(-1, 3)
    keys = np.round(corners / _WELD_MM).astype(np.int64)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    vertices = unique.astype(float) * _WELD_MM
    faces = inverse.reshape(-1, 3)
    keep = (
        (faces[:, 0] != faces[:, 1])
        & (faces[:, 1] != faces[:, 2])
        & (faces[:, 0] != faces[:, 2])
    )
    return vertices, faces[keep]


def _edge_faces(faces: np.ndarray) -> dict[tuple[int, int], list[int]]:
    """Each undirected edge and the faces that use it."""
    table: dict[tuple[int, int], list[int]] = {}
    for index, (a, b, c) in enumerate(faces.tolist()):
        for p, q in ((a, b), (b, c), (c, a)):
            key = (p, q) if p < q else (q, p)
            table.setdefault(key, []).append(index)
    return table


def _components(members: np.ndarray, links: list[tuple[int, int]]) -> list[list[int]]:
    """Connected groups of ``members`` (indices) joined by ``links``."""
    parent = {int(m): int(m) for m in members}

    def root(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for a, b in links:
        if a in parent and b in parent:
            parent[root(a)] = root(b)
    groups: dict[int, list[int]] = {}
    for item in parent:
        groups.setdefault(root(item), []).append(item)
    return list(groups.values())


class _Mesh:
    """A welded mesh seen from one build direction."""

    def __init__(self, triangles: np.ndarray, direction: np.ndarray) -> None:
        self.vertices, self.faces = _weld(triangles)
        self.d = direction
        self.h = self.vertices @ direction
        self.h0 = float(self.h.min()) if len(self.h) else 0.0
        a, b, c = (self.vertices[self.faces[:, i]] for i in range(3))
        cross = np.cross(b - a, c - a)
        doubled = np.linalg.norm(cross, axis=1)
        self.area = doubled / 2.0
        self.normal = cross / np.where(doubled > 0, doubled, 1.0)[:, None]
        self.centre = (a + b + c) / 3.0
        self.corners = (a, b, c)
        facing = self.normal @ direction
        on_plate = (self.h[self.faces] <= self.h0 + PLATE_MM).all(axis=1)
        self.down = (facing < -1e-6) & ~on_plate
        self.angle = np.degrees(np.arccos(np.clip(-facing, -1.0, 1.0)))
        self.edges = _edge_faces(self.faces)
        # Two directions across the build direction, for the side rays.
        helper = np.array([1.0, 0.0, 0.0])
        if abs(float(direction @ helper)) > 0.9:
            helper = np.array([0.0, 1.0, 0.0])
        self.e1 = np.cross(direction, helper)
        self.e1 /= np.linalg.norm(self.e1)
        self.e2 = np.cross(direction, self.e1)

    def regions(self, mask: np.ndarray) -> list[list[int]]:
        """The faces under ``mask``, grouped by shared edges."""
        members = np.flatnonzero(mask)
        chosen = set(members.tolist())
        links = [
            (users[0], users[1])
            for users in self.edges.values()
            if len(users) == 2 and users[0] in chosen and users[1] in chosen
        ]
        return _components(members, links)

    def supported_runs(self, region: list[int]) -> list[list[tuple[int, int]]]:
        """The region's supported boundary edges, chained into runs."""
        inside = set(region)
        supported: list[tuple[int, int]] = []
        for face in region:
            a, b, c = self.faces[face].tolist()
            for p, q in ((a, b), (b, c), (c, a)):
                key = (p, q) if p < q else (q, p)
                outside = [f for f in self.edges.get(key, []) if f not in inside]
                if outside and self._goes_down(outside[0], key):
                    supported.append(key)
        by_vertex: dict[int, list[int]] = {}
        for index, (p, q) in enumerate(supported):
            by_vertex.setdefault(p, []).append(index)
            by_vertex.setdefault(q, []).append(index)
        links = [
            (users[0], other) for users in by_vertex.values() for other in users[1:]
        ]
        groups = _components(np.arange(len(supported)), links)
        return [[supported[i] for i in group] for group in groups]

    def touches_plate(self, region: list[int]) -> bool:
        """Whether a region reaches down to the plate, which holds it."""
        return bool((self.h[self.faces[region]] <= self.h0 + PLATE_MM).any())

    def _goes_down(self, face: int, edge: tuple[int, int]) -> bool:
        """Whether ``face`` reaches below ``edge``: a wall under the edge."""
        third = [v for v in self.faces[face].tolist() if v not in edge]
        floor = min(self.h[edge[0]], self.h[edge[1]])
        return bool(third) and float(self.h[third[0]]) < floor - _LEVEL_MM

    def local_minima(self) -> list[int]:
        """Vertices above the plate lower than all their neighbours."""
        lowest: dict[int, float] = {}
        for p, q in self.edges:
            lowest[p] = min(lowest.get(p, math.inf), float(self.h[q]))
            lowest[q] = min(lowest.get(q, math.inf), float(self.h[p]))
        return [
            v
            for v, neighbour in lowest.items()
            if self.h[v] > self.h0 + PLATE_MM and self.h[v] < neighbour - _LEVEL_MM
        ]

    def hits(self, origin: np.ndarray, direction: np.ndarray) -> bool:
        """Whether a ray from ``origin`` hits the mesh (Moller-Trumbore)."""
        a, b, c = self.corners
        edge1, edge2 = b - a, c - a
        p = np.cross(direction, edge2)
        det = np.einsum("ij,ij->i", edge1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = origin - a
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, edge1)
        v = (q @ direction) * inv
        t = np.einsum("ij,ij->i", edge2, q) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
        return bool(hit.any())


def _rounded(values: Any) -> list[float]:
    return [round(float(v), 3) + 0.0 for v in values]


def _span(mesh: _Mesh, region: list[int], runs: list[list[tuple[int, int]]]) -> float:
    """Twice the furthest a point of the region is from its nearest support.

    The points are each triangle's centre and edge midpoints: a long thin
    triangle's centre alone sits a third of the way along it.
    """
    across = np.eye(3) - np.outer(mesh.d, mesh.d)
    starts = np.array([mesh.vertices[p] for run in runs for p, _q in run]) @ across
    ends = np.array([mesh.vertices[q] for run in runs for _p, q in run]) @ across
    a, b, c = (corner[region] for corner in mesh.corners)
    centres = np.vstack([mesh.centre[region], (a + b) / 2, (b + c) / 2, (c + a) / 2])
    centres = centres @ across
    seg = ends - starts
    length2 = np.einsum("ij,ij->i", seg, seg)
    rel = centres[:, None, :] - starts[None, :, :]
    t = np.clip(
        np.einsum("kij,ij->ki", rel, seg) / np.where(length2 > 0, length2, 1.0),
        0.0,
        1.0,
    )
    nearest = starts[None, :, :] + t[:, :, None] * seg[None, :, :]
    distance = np.linalg.norm(centres[:, None, :] - nearest, axis=2).min(axis=1)
    return 2.0 * float(distance.max())


def _listed(entries: list[dict[str, Any]], key: str) -> dict[str, Any]:
    entries.sort(key=lambda e: -float(e[key]))
    return {"count": len(entries), "items": entries[:MAX_LISTED]}


def analyse(
    triangles: Sequence[Sequence[float]] | np.ndarray,
    build_direction: str | Sequence[float],
    support_angle_deg: float = 45.0,
    min_bridge_mm: float = 5.0,
) -> dict[str, Any]:
    """Check a mesh for printing with ``build_direction`` away from the plate.

    Args:
        triangles: Each triangle's three vertices, in mm (nine numbers).
        build_direction: The direction the part grows from the plate.
        support_angle_deg: Down-facing surfaces under this angle from
            horizontal need supports.
        min_bridge_mm: Only bridges longer than this are listed.

    Returns:
        dict[str, Any]: ``down_facing`` (area per band, ``needs_support_mm2``),
        ``islands``, ``bridges`` and ``suction_cups`` (each ``count`` and up
        to :data:`MAX_LISTED` ``items``), ``ok`` and ``triangles``.

    Raises:
        ValueError: An empty mesh or a bad build direction.
    """
    direction = direction_vector(build_direction)
    corners = np.asarray(triangles, dtype=float).reshape(-1, 3, 3)
    if len(corners) == 0:
        raise ValueError("The mesh has no triangles.")
    mesh = _Mesh(corners, direction)

    bands = [
        {
            "from_deg": low,
            "to_deg": high,
            "area_mm2": round(
                float(
                    mesh.area[
                        mesh.down
                        & (mesh.angle >= low)
                        & ((mesh.angle < high) if high < 90 else True)
                    ].sum()
                ),
                3,
            ),
        }
        for low, high in BANDS
    ]
    needs = mesh.down & (mesh.angle < support_angle_deg)

    islands: list[dict[str, Any]] = []
    cups: list[dict[str, Any]] = []
    in_islands: set[int] = set()
    for region in mesh.regions(needs):
        if not mesh.touches_plate(region) and not mesh.supported_runs(region):
            region_vertices = np.unique(mesh.faces[region])
            lowest = region_vertices[np.argmin(mesh.h[region_vertices])]
            in_islands.update(region_vertices.tolist())
            islands.append(
                {
                    "lowest_point_mm": _rounded(mesh.vertices[lowest]),
                    "area_mm2": round(float(mesh.area[region].sum()), 3),
                }
            )
        cup = _cup(mesh, region)
        if cup is not None:
            cups.append(cup)
    for vertex in mesh.local_minima():
        if vertex not in in_islands:
            islands.append(
                {"lowest_point_mm": _rounded(mesh.vertices[vertex]), "area_mm2": 0.0}
            )

    bridges: list[dict[str, Any]] = []
    for region in mesh.regions(mesh.down & (mesh.angle < FLAT_DEG)):
        runs = mesh.supported_runs(region)
        if len(runs) < 2:
            continue
        span = _span(mesh, region, runs)
        if span > min_bridge_mm:
            weights = mesh.area[region]
            centre = (mesh.centre[region] * weights[:, None]).sum(
                axis=0
            ) / weights.sum()
            bridges.append(
                {
                    "span_mm": round(span, 3),
                    "center_mm": _rounded(centre),
                    "area_mm2": round(float(weights.sum()), 3),
                }
            )

    needs_support = round(float(mesh.area[needs].sum()), 3)
    return {
        "build_direction": _rounded(direction),
        "support_angle_deg": support_angle_deg,
        "triangles": int(len(mesh.faces)),
        "down_facing": {"bands": bands, "needs_support_mm2": needs_support},
        "islands": _listed(islands, "area_mm2"),
        "bridges": _listed(bridges, "span_mm"),
        "suction_cups": _listed(cups, "opening_area_mm2"),
        "ok": not islands and not cups and not bridges and needs_support == 0.0,
    }


def _cup(mesh: _Mesh, region: list[int]) -> dict[str, Any] | None:
    """A ceiling region as a suction cup, or None when it vents or is closed."""
    weights = mesh.area[region]
    centre = (mesh.centre[region] * weights[:, None]).sum(axis=0) / weights.sum()
    start = centre - PLATE_MM * mesh.d
    sideways = (mesh.e1, -mesh.e1, mesh.e2, -mesh.e2)
    if not all(mesh.hits(start, ray) for ray in sideways):
        return None
    if mesh.hits(start, -mesh.d):
        return None  # closed toward the plate: an enclosed void, not a cup
    facing = np.abs(mesh.normal[region] @ mesh.d)
    return {
        "opening_center_mm": _rounded(centre),
        "opening_area_mm2": round(float((weights * facing).sum()), 3),
        "depth_mm": round(float(centre @ mesh.d) - mesh.h0, 3),
    }
