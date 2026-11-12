"""Check an STL file's mesh: triangles, watertightness, volume and size.

Pure Python and no COM, so it can read the file an export just wrote. Binary
and ASCII STL are both read. SolidWorks writes each triangle with its own
three vertices, so vertices are welded (snapped to a 0.001 mm grid) before the
edges are counted: in a closed mesh every edge is shared by exactly two
triangles. The file carries no units; the caller says which unit it was
written in (``swExportStlUnits`` for a SolidWorks export) and the results are
in mm.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Iterator
from typing import IO, Any

#: Millimetres per unit, for each unit SolidWorks writes STL in.
MM_PER_UNIT = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}

#: Vertices are snapped to a grid this fine, in mm, before edges are counted.
WELD_MM = 1e-3

#: Larger meshes are not checked: a million triangles took 3 s and about
#: 300 MB (a 50 MB binary file, finer than most prints need).
MAX_TRIANGLES = 1_000_000

_HEADER = 80
_RECORD = struct.Struct("<12fH")  # normal, three vertices, attribute bytes

#: A triangle's three vertices: x1, y1, z1, x2, ..., z3.
Triangle = tuple[float, ...]


class _TooLarge(ValueError):
    """The mesh has more than :data:`MAX_TRIANGLES` triangles."""


def _binary_triangles(handle: IO[bytes], count: int) -> Iterator[Triangle]:
    """The triangles of a binary STL after its header, without the normals."""
    for record in _RECORD.iter_unpack(handle.read(_RECORD.size * count)):
        yield record[3:12]


def _ascii_triangles(lines: Iterable[bytes]) -> Iterator[Triangle]:
    """The triangles of an ASCII STL, from its ``vertex x y z`` lines.

    Raises:
        ValueError: A vertex that isn't three numbers, or a facet without
            three vertices.
    """
    facets = 0
    corners: list[float] = []
    for line in lines:
        words = line.split()
        keyword = words[0].lower() if words else b""
        if keyword == b"facet":
            facets += 1
        elif keyword == b"vertex":
            if len(words) != 4:
                raise ValueError(f"an STL vertex line isn't three numbers: {line!r}")
            corners.extend(float(word) for word in words[1:])
        elif keyword == b"endfacet":
            if len(corners) != 9:
                raise ValueError(
                    f"STL facet {facets} has {len(corners) // 3} vertices, not 3"
                )
            yield tuple(corners)
            corners = []


def _triangles(handle: IO[bytes]) -> Iterator[Triangle]:
    """The triangles of an open binary or ASCII STL file.

    A binary file is 84 bytes plus 50 per triangle. Some binary headers start
    with ``solid`` like an ASCII file, so the size decides first.

    Raises:
        ValueError: When the file is neither.
    """
    size = os.fstat(handle.fileno()).st_size
    head = handle.read(_HEADER + 4)
    full = len(head) == _HEADER + 4
    count = struct.unpack_from("<I", head, _HEADER)[0] if full else -1
    expected = _HEADER + 4 + _RECORD.size * count
    is_ascii = head.lstrip()[:5].lower() == b"solid"
    if count >= 0 and (size == expected or (size > expected and not is_ascii)):
        if count > MAX_TRIANGLES:
            raise _TooLarge()
        return _binary_triangles(handle, count)
    if is_ascii:
        handle.seek(0)
        return _ascii_triangles(handle)
    raise ValueError("it is not an STL: not a binary STL's size, and no 'solid' header")


def _measure(triangles: Iterable[Triangle], mm_per_unit: float) -> dict[str, Any]:
    """Weld the vertices, count the edges, and add up the volume and size.

    Args:
        triangles: Each triangle's three vertices, in file units.
        mm_per_unit: Millimetres per file unit.

    Returns:
        dict[str, Any]: The mesh check, in mm.
    """
    snap = mm_per_unit / WELD_MM
    vertices: dict[tuple[int, int, int], int] = {}
    edges: dict[int, int] = {}
    six_volume = 0.0
    count = 0
    for x1, y1, z1, x2, y2, z2, x3, y3, z3 in triangles:
        count += 1
        if count > MAX_TRIANGLES:
            raise _TooLarge()
        # The signed volume of the tetrahedron to the origin, times six.
        six_volume += (
            x1 * (y2 * z3 - z2 * y3)
            - y1 * (x2 * z3 - z2 * x3)
            + z1 * (x2 * y3 - y2 * x3)
        )
        a = vertices.setdefault(
            (round(x1 * snap), round(y1 * snap), round(z1 * snap)), len(vertices)
        )
        b = vertices.setdefault(
            (round(x2 * snap), round(y2 * snap), round(z2 * snap)), len(vertices)
        )
        c = vertices.setdefault(
            (round(x3 * snap), round(y3 * snap), round(z3 * snap)), len(vertices)
        )
        if a == b or b == c or a == c:
            continue  # a sliver the weld collapsed: its neighbours share the edge
        for p, q in ((a, b), (b, c), (c, a)):
            key = (p << 32 | q) if p < q else (q << 32 | p)
            edges[key] = edges.get(key, 0) + 1
    open_edges = sum(1 for used in edges.values() if used == 1)
    non_manifold = sum(1 for used in edges.values() if used > 2)
    size = None
    if vertices:
        size = [
            round((max(axis) - min(axis)) * WELD_MM, 3)
            for axis in zip(*vertices, strict=True)
        ]
    return {
        "triangles": count,
        "closed": bool(edges) and open_edges == 0 and non_manifold == 0,
        "open_edges": open_edges,
        "non_manifold_edges": non_manifold,
        "volume_mm3": round(abs(six_volume) / 6.0 * mm_per_unit**3, 3),
        "size_mm": size,
    }


def check_stl(path: str | os.PathLike[str], units: str | None) -> dict[str, Any]:
    """Read an STL file and check its mesh; never raises.

    Args:
        path: The ``.stl`` file.
        units: The unit the file was written in (``mm``, ``cm``, ``m``,
            ``in`` or ``ft``); ``None`` when not known, and then the file is
            read as mm and a ``note`` says so.

    Returns:
        dict[str, Any]: ``triangles``; ``closed`` (every edge shared by
        exactly two triangles); ``open_edges`` (used by one triangle) and
        ``non_manifold_edges`` (by more than two); ``volume_mm3``; ``size_mm``
        (``[x, y, z]`` extents, ``None`` for no triangles); and ``units``.
        ``{"error": ...}`` alone when the file can't be read or checked.
    """
    if units is not None and units not in MM_PER_UNIT:
        return {"error": f"Unknown STL units {units!r}; the mesh was not checked."}
    try:
        with open(path, "rb") as handle:
            check = _measure(_triangles(handle), MM_PER_UNIT[units or "mm"])
    except _TooLarge:
        return {
            "error": (
                f"The mesh has more than {MAX_TRIANGLES} triangles, too many "
                "to check here."
            )
        }
    except (OSError, ValueError, OverflowError) as exc:
        return {"error": f"Could not check the STL file {os.fspath(path)}: {exc}"}
    check["units"] = units
    if units is None:
        check["note"] = "The file's units are unknown; it was read as mm."
    return check
