"""The print-orientation check on a mesh (``utils.printability``).

Meshes are built from cells of a grid: every face between a filled cell and
an empty one becomes two outward-facing triangles, so the mesh is closed and
shares its edges, like a welded SolidWorks STL.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence

import numpy as np
import pytest

from solidworks_mcp.utils import printability as pr

Cell = tuple[int, int, int]


def _cells_mesh(
    xs: Sequence[float],
    ys: Sequence[float],
    zs: Sequence[float],
    filled: Iterable[Cell],
) -> list[list[float]]:
    """Outward triangles bounding the filled cells of the grid xs × ys × zs."""
    full = set(filled)
    grid = (xs, ys, zs)
    triangles: list[list[float]] = []
    for cell in full:
        for axis, step in itertools.product(range(3), (-1, 1)):
            neighbour = list(cell)
            neighbour[axis] += step
            if tuple(neighbour) in full:
                continue
            u, v = [a for a in range(3) if a != axis]
            level = grid[axis][cell[axis] + (1 if step > 0 else 0)]
            corners = []
            for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                point = [0.0, 0.0, 0.0]
                point[axis] = level
                point[u] = grid[u][cell[u] + du]
                point[v] = grid[v][cell[v] + dv]
                corners.append(point)
            # (u, v, axis) right-handed when axis follows v cyclically.
            outward = step > 0 if (axis - v) % 3 == 1 else step < 0
            a, b, c, d = corners if outward else corners[::-1]
            triangles += [[*a, *b, *c], [*a, *c, *d]]
    return triangles


def _block() -> list[list[float]]:
    return _cells_mesh([0, 40], [0, 20], [0, 10], [(0, 0, 0)])


def _shelf() -> list[list[float]]:
    """A 10 x 20 x 20 post with a 10 x 20 shelf sticking out, underside at 8."""
    filled = [(0, 0, 0), (0, 0, 1), (0, 0, 2), (1, 0, 1)]
    return _cells_mesh([0, 10, 20], [0, 20], [0, 8, 10, 20], filled)


def _pocket_box() -> list[list[float]]:
    """A 30 mm cube with a 20 x 20 x 15 pocket open on its bottom face."""
    filled = [
        (i, j, k)
        for i, j, k in itertools.product(range(3), range(3), range(2))
        if (i, j, k) != (1, 1, 0)
    ]
    return _cells_mesh([0, 5, 25, 30], [0, 5, 25, 30], [0, 15, 30], filled)


def _bridge() -> list[list[float]]:
    """Two 5 mm pillars 20 mm apart, joined by a beam 10 up: a 20 mm bridge."""
    filled = [(0, 0, 0), (2, 0, 0), (0, 0, 1), (1, 0, 1), (2, 0, 1)]
    return _cells_mesh([0, 5, 25, 30], [0, 10], [0, 10, 15], filled)


def _pendant() -> list[list[float]]:
    """The bridge with a block hanging from the beam's middle, 5 above the plate."""
    xs, zs = [0, 5, 12, 18, 25, 30], [0, 5, 10, 15]
    pillars = [(i, 0, k) for i in (0, 4) for k in (0, 1)]
    beam = [(i, 0, 2) for i in range(5)]
    return _cells_mesh(xs, [0, 10], zs, [*pillars, *beam, (2, 0, 1)])


def _octahedron(centre: Sequence[float], a: float) -> list[list[float]]:
    """A closed octahedron, its points a from ``centre`` along each axis."""
    cx, cy, cz = centre
    triangles = []
    for sx, sy, sz in itertools.product((-1, 1), repeat=3):
        x = [cx + sx * a, cy, cz]
        y = [cx, cy + sy * a, cz]
        z = [cx, cy, cz + sz * a]
        order = (x, y, z) if sx * sy * sz > 0 else (x, z, y)
        triangles.append([c for point in order for c in point])
    return triangles


def _band(result: dict, low: float) -> float:
    return next(
        b["area_mm2"] for b in result["down_facing"]["bands"] if b["from_deg"] == low
    )


# ---- build direction ---------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("z", [0, 0, 1]),
        (" -X ", [-1, 0, 0]),
        ("+y", [0, 1, 0]),
        ([0, 0, -2], [0, 0, -1]),
    ],
)
def test_a_direction_by_name_or_vector(value, expected) -> None:
    assert pr.direction_vector(value).tolist() == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        ("up", "must be x, y, z"),
        ([1, 0], "must be [x, y, z]"),
        ([0, 0, 0], "zero vector"),
    ],
)
def test_a_bad_direction_is_refused(value, fragment) -> None:
    with pytest.raises(ValueError, match=None) as caught:
        pr.direction_vector(value)
    assert fragment in str(caught.value)


def test_an_empty_mesh_is_refused() -> None:
    with pytest.raises(ValueError, match="no triangles"):
        pr.analyse([], "z")


# ---- the spec's scenarios ----------------------------------------------------


def test_a_block_printed_flat_is_fine() -> None:
    result = pr.analyse(_block(), "z")

    assert result["ok"] is True
    assert result["down_facing"]["needs_support_mm2"] == 0.0
    assert all(b["area_mm2"] == 0.0 for b in result["down_facing"]["bands"])
    for kind in ("islands", "bridges", "suction_cups"):
        assert result[kind] == {"count": 0, "items": []}
    assert result["triangles"] == 12


@pytest.mark.parametrize("direction", ["-y", "x"])
def test_a_block_on_its_side_has_no_overhang_either(direction: str) -> None:
    result = pr.analyse(_block(), direction)

    assert result["ok"] is True


def test_an_overhanging_shelf_needs_supports() -> None:
    result = pr.analyse(_shelf(), "z")

    assert _band(result, 0.0) == pytest.approx(200.0)
    assert result["down_facing"]["needs_support_mm2"] == pytest.approx(200.0)
    assert result["islands"]["count"] == 0  # held by the post
    assert result["bridges"]["count"] == 0  # held on one side only
    assert result["suction_cups"]["count"] == 0  # open on three sides
    assert result["ok"] is False


def test_a_pocket_open_toward_the_plate_is_a_suction_cup() -> None:
    upright = pr.analyse(_pocket_box(), "z")
    flipped = pr.analyse(_pocket_box(), "-z")

    assert upright["suction_cups"]["count"] == 1
    cup = upright["suction_cups"]["items"][0]
    assert cup["depth_mm"] == pytest.approx(15.0)
    assert cup["opening_area_mm2"] == pytest.approx(400.0)
    assert cup["opening_center_mm"] == pytest.approx([15.0, 15.0, 15.0])
    assert upright["islands"]["count"] == 0
    assert flipped["suction_cups"]["count"] == 0
    assert flipped["ok"] is True  # printed pocket-up, nothing overhangs


def test_a_beam_between_two_pillars_is_a_bridge() -> None:
    result = pr.analyse(_bridge(), "z")

    assert result["bridges"]["count"] == 1
    bridge = result["bridges"]["items"][0]
    assert bridge["span_mm"] == pytest.approx(20.0)
    assert bridge["center_mm"] == pytest.approx([15.0, 5.0, 10.0])
    assert bridge["area_mm2"] == pytest.approx(200.0)
    assert result["suction_cups"]["count"] == 0  # open front and back
    assert result["islands"]["count"] == 0


def test_a_short_bridge_is_not_listed() -> None:
    result = pr.analyse(_bridge(), "z", min_bridge_mm=25.0)

    assert result["bridges"]["count"] == 0
    assert result["ok"] is False  # it still needs supports under the beam


def test_a_block_hanging_from_a_beam_is_an_island() -> None:
    result = pr.analyse(_pendant(), "z")

    assert result["islands"]["count"] == 1
    island = result["islands"]["items"][0]
    assert island["lowest_point_mm"][2] == pytest.approx(5.0)
    assert island["area_mm2"] == pytest.approx(60.0)


def test_a_pointed_underside_is_an_island_point() -> None:
    """Steep faces need no support, but the tip starts in mid-air."""
    mesh = [*_block(), *_octahedron([20, 10, 30], 3.0)]

    result = pr.analyse(mesh, "z")

    assert result["down_facing"]["needs_support_mm2"] == 0.0
    assert _band(result, 45.0) > 0
    assert result["islands"]["items"] == [
        {"lowest_point_mm": [20.0, 10.0, 27.0], "area_mm2": 0.0}
    ]
    assert result["ok"] is False


def test_a_support_angle_moves_the_line() -> None:
    mesh = [*_block(), *_octahedron([20, 10, 30], 3.0)]

    strict = pr.analyse(mesh, "z", support_angle_deg=60.0)

    assert strict["down_facing"]["needs_support_mm2"] > 0


def test_lists_are_capped_but_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pr, "MAX_LISTED", 2)
    entries = [{"area_mm2": float(n)} for n in range(5)]

    listed = pr._listed(entries, "area_mm2")

    assert listed["count"] == 5
    assert [e["area_mm2"] for e in listed["items"]] == [4.0, 3.0]


def test_a_vector_direction_off_the_axes() -> None:
    result = pr.analyse(_block(), [0, 0.1, 1])

    assert result["build_direction"] == pytest.approx(
        list(np.array([0, 0.1, 1]) / np.linalg.norm([0, 0.1, 1])), abs=1e-3
    )
