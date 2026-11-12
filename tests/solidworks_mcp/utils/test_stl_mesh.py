"""The STL mesh check ``export_stl`` returns (``utils.stl_mesh``)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from solidworks_mcp.utils import stl_mesh
from solidworks_mcp.utils.stl_mesh import check_stl

Triangle = tuple[float, ...]

# A unit cube's faces, each corner list counter-clockwise seen from outside.
_FACES = (
    ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
    ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
    ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
    ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
    ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
    ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),
)


def _cube(side: float = 10.0, at: tuple[float, float, float] = (0, 0, 0)) -> list:
    """The 12 triangles of a cube, as SolidWorks writes them: own vertices each."""

    def corner(c: tuple[int, int, int]) -> tuple[float, ...]:
        return tuple(at[i] + side * c[i] for i in range(3))

    triangles: list[Triangle] = []
    for p0, p1, p2, p3 in _FACES:
        triangles.append((*corner(p0), *corner(p1), *corner(p2)))
        triangles.append((*corner(p0), *corner(p2), *corner(p3)))
    return triangles


def _binary(path: Path, triangles: list, header: bytes = b"binary STL") -> Path:
    data = header.ljust(80, b" ") + struct.pack("<I", len(triangles))
    for t in triangles:
        data += struct.pack("<12fH", 0.0, 0.0, 0.0, *t, 0)
    path.write_bytes(data)
    return path


def _ascii(path: Path, triangles: list) -> Path:
    lines = ["solid test"]
    for t in triangles:
        lines += ["  facet normal 0 0 0", "    outer loop"]
        lines += [
            f"      vertex {t[i]:.10e} {t[i + 1]:.10e} {t[i + 2]:.10e}"
            for i in (0, 3, 6)
        ]
        lines += ["    endloop", "  endfacet"]
    lines.append("endsolid test")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


_CLOSED_CUBE = {
    "triangles": 12,
    "closed": True,
    "open_edges": 0,
    "non_manifold_edges": 0,
    "volume_mm3": 1000.0,
    "size_mm": [10.0, 10.0, 10.0],
    "units": "mm",
}


@pytest.mark.parametrize("write", [_binary, _ascii])
def test_a_closed_cube_is_closed_in_binary_and_ascii(tmp_path: Path, write) -> None:
    path = write(tmp_path / "cube.stl", _cube(at=(5.0, -3.0, 2.0)))

    assert check_stl(path, "mm") == _CLOSED_CUBE


def test_a_cube_missing_a_face_has_four_open_edges(tmp_path: Path) -> None:
    path = _binary(tmp_path / "open.stl", _cube()[2:])

    check = check_stl(path, "mm")

    assert check["triangles"] == 10
    assert check["closed"] is False
    assert (check["open_edges"], check["non_manifold_edges"]) == (4, 0)


def test_two_cubes_touching_on_an_edge_are_non_manifold(tmp_path: Path) -> None:
    triangles = _cube() + _cube(at=(10.0, 10.0, 0.0))
    path = _ascii(tmp_path / "pair.stl", triangles)

    check = check_stl(path, "mm")

    assert check["closed"] is False
    assert (check["open_edges"], check["non_manifold_edges"]) == (0, 1)
    assert check["volume_mm3"] == 2000.0
    assert check["size_mm"] == [20.0, 20.0, 10.0]


@pytest.mark.parametrize(
    ("units", "side", "size_mm", "volume_mm3"),
    [
        ("in", 1.0, 25.4, 16387.064),
        ("m", 0.01, 10.0, 1000.0),
        ("cm", 1.0, 10.0, 1000.0),
        ("ft", 0.5, 152.4, 3539605.824),
    ],
)
def test_sizes_and_volume_are_in_mm_whatever_the_file_units(
    tmp_path: Path, units: str, side: float, size_mm: float, volume_mm3: float
) -> None:
    path = _ascii(tmp_path / "cube.stl", _cube(side=side))

    check = check_stl(path, units)

    assert check["closed"] is True
    assert check["size_mm"] == [size_mm] * 3
    assert check["volume_mm3"] == pytest.approx(volume_mm3, rel=1e-6)
    assert check["units"] == units


def test_unknown_units_are_read_as_mm_and_said_so(tmp_path: Path) -> None:
    check = check_stl(_binary(tmp_path / "c.stl", _cube()), None)

    assert check["size_mm"] == [10.0, 10.0, 10.0]
    assert check["units"] is None
    assert "read as mm" in check["note"]


def test_vertices_a_rounding_apart_are_welded(tmp_path: Path) -> None:
    triangles = _cube()
    jittered = list(triangles[0])
    jittered[0] += 1e-7
    triangles[0] = tuple(jittered)
    # A sliver the weld collapses to a line is skipped, not counted as open.
    triangles.append((0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 0.0, 1e-7))

    check = check_stl(_ascii(tmp_path / "c.stl", triangles), "mm")

    assert check["triangles"] == 13
    assert check["closed"] is True


def test_a_binary_header_starting_with_solid_is_still_binary(tmp_path: Path) -> None:
    path = _binary(tmp_path / "c.stl", _cube(), header=b"solid Part1 (binary)")

    assert check_stl(path, "mm") == _CLOSED_CUBE


def test_bytes_after_the_last_binary_triangle_are_ignored(tmp_path: Path) -> None:
    path = _binary(tmp_path / "c.stl", _cube())
    path.write_bytes(path.read_bytes() + b"\x00" * 7)

    assert check_stl(path, "mm")["closed"] is True


def test_a_file_with_no_triangles(tmp_path: Path) -> None:
    check = check_stl(_binary(tmp_path / "empty.stl", []), "mm")

    assert check["triangles"] == 0
    assert check["closed"] is False
    assert check["size_mm"] is None
    assert check["volume_mm3"] == 0.0


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        (b"not a mesh at all", "it is not an STL"),
        (b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 1 2\n", "three numbers"),
        (
            b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n"
            b"vertex 1 0 0\nendloop\nendfacet\nendsolid x\n",
            "facet 1 has 2 vertices",
        ),
        (b"solid x\nfacet\nvertex 0 0 zero\n", "could not convert"),
    ],
)
def test_a_file_that_is_not_a_readable_stl_is_an_error(
    tmp_path: Path, content: bytes, fragment: str
) -> None:
    path = tmp_path / "bad.stl"
    path.write_bytes(content)

    check = check_stl(path, "mm")

    assert list(check) == ["error"]
    assert "Could not check the STL file" in check["error"]
    assert fragment in check["error"]


def test_a_truncated_binary_file_is_an_error(tmp_path: Path) -> None:
    path = _binary(tmp_path / "cut.stl", _cube())
    path.write_bytes(path.read_bytes()[:-60])

    assert "it is not an STL" in check_stl(path, "mm")["error"]


def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    check = check_stl(tmp_path / "gone.stl", "mm")

    assert "Could not check the STL file" in check["error"]


def test_an_infinite_coordinate_is_an_error(tmp_path: Path) -> None:
    triangles = _cube()
    triangles[0] = (float("inf"), *triangles[0][1:])

    assert (
        "Could not check"
        in check_stl(_binary(tmp_path / "i.stl", triangles), "mm")["error"]
    )


def test_unknown_units_are_refused(tmp_path: Path) -> None:
    check = check_stl(_binary(tmp_path / "c.stl", _cube()), "furlong")

    assert check == {"error": "Unknown STL units 'furlong'; the mesh was not checked."}


@pytest.mark.parametrize("write", [_binary, _ascii])
def test_a_mesh_too_large_to_check_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write
) -> None:
    monkeypatch.setattr(stl_mesh, "MAX_TRIANGLES", 5)

    check = check_stl(write(tmp_path / "big.stl", _cube()), "mm")

    assert check == {
        "error": "The mesh has more than 5 triangles, too many to check here."
    }
