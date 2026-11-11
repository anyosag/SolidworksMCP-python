"""Wall thickness of the active part, for 3D printing: the "ray method".

Points are sampled on every face from SolidWorks' display tessellation
(``IFace2.GetTessTriangles`` / ``GetTessNorms``). From each point a ray is
cast inward, against the outward normal, and the distance to where it
leaves the solid is the wall's local thickness there. One
``IModelDocExtension.RayIntersections`` call casts every ray;
``IModelDoc2.GetRayIntersectionsPoints`` returns 9 numbers per hit (body
index, ray index, hit type, x, y, z, then the normal), all in metres.

The pure pieces (sampling, reading hits, the summary) are separate from the
COM call so they can be tested without SolidWorks.

Limits, stated in the reply too: a ray measures along the normal, so a
point on a fillet or near an edge can read a little thin or thick; a face
the tessellation covers with few triangles gets few samples.
"""

from __future__ import annotations

import math
from typing import Any

from . import limits
from .com_utils import as_list
from .com_utils import attempt as _attempt
from .com_utils import flag as _flag

#: ``swRayPtsOpts_e.swRayPtsOptsENTRY_EXIT`` (swconst.tlb, SW 2026): report
#: whether each hit enters or leaves a body.
RAY_ENTRY_EXIT = 4
#: ``swRayPtsResults_e.swRayPtsResultsEXIT``: the ray leaves the body there.
HIT_EXIT = 32

#: Numbers per hit in ``GetRayIntersectionsPoints``.
_HIT_STRIDE = 9
#: How far inside the face a ray starts, metres: past the face itself, far
#: below any printable wall.
_START_INSIDE_M = 1e-6
#: ``RayIntersections``' hit radius, metres (the value CodeStack's example uses).
_HIT_RADIUS_M = 1e-8

#: The most rays one check casts, and the most thin spots a reply lists.
MAX_RAYS = 5000
MAX_THIN_SPOTS = 20


def _unit(vector: list[float]) -> list[float] | None:
    length = math.sqrt(sum(c * c for c in vector))
    if length < 1e-12:
        return None
    return [c / length for c in vector]


def sample_points(
    triangles: Any, normals: Any
) -> list[tuple[list[float], list[float]]]:
    """Sample points and outward normals from one face's tessellation.

    Each triangle gives its centroid and the three points halfway from the
    centroid to a corner (none on an edge of the face), with the triangle's
    averaged vertex normal.

    Args:
        triangles: ``GetTessTriangles``: 9 numbers per triangle (three
            corners, x y z each), metres.
        normals: ``GetTessNorms``: 9 numbers per triangle (a normal per
            corner).

    Returns:
        list[tuple[list[float], list[float]]]: ``(point, unit normal)`` pairs.
    """
    tri = [float(v) for v in as_list(triangles)]
    nor = [float(v) for v in as_list(normals)]
    samples = []
    for start in range(0, min(len(tri), len(nor)) - 8, 9):
        corners = [tri[start + 3 * k : start + 3 * k + 3] for k in range(3)]
        normal = _unit(
            [sum(nor[start + 3 * k + axis] for k in range(3)) for axis in range(3)]
        )
        if normal is None:
            continue
        centroid = [sum(c[axis] for c in corners) / 3 for axis in range(3)]
        samples.append((centroid, normal))
        for corner in corners:
            samples.append(
                ([(m + c) / 2 for m, c in zip(centroid, corner, strict=True)], normal)
            )
    return samples


def thin_out(samples: list[Any], limit: int) -> list[Any]:
    """Every n-th sample, so at most ``limit`` are kept, spread over all faces."""
    if len(samples) <= limit:
        return samples
    step = len(samples) / limit
    return [samples[int(i * step)] for i in range(limit)]


def ray_arrays(
    samples: list[tuple[list[float], list[float]]],
) -> tuple[list[float], list[float]]:
    """Flat start points and directions (x y z per ray) for ``RayIntersections``.

    Each ray starts just inside its face and points against the normal.
    """
    starts: list[float] = []
    directions: list[float] = []
    for point, normal in samples:
        starts += [p - n * _START_INSIDE_M for p, n in zip(point, normal, strict=True)]
        directions += [-n for n in normal]
    return starts, directions


def exit_distances(
    hits: Any, samples: list[tuple[list[float], list[float]]]
) -> dict[int, float]:
    """The first exit along each ray, as a distance from its sample point (m).

    Args:
        hits: ``GetRayIntersectionsPoints``: 9 numbers per hit.
        samples: The ``(point, normal)`` each ray was cast from.

    Returns:
        dict[int, float]: Ray index -> wall thickness in metres. A ray with no
        exit (it hit nothing) is absent.
    """
    values = [float(v) for v in as_list(hits)]
    found: dict[int, float] = {}
    for start in range(0, len(values) - _HIT_STRIDE + 1, _HIT_STRIDE):
        ray = int(values[start + 1])
        kind = int(values[start + 2])
        if ray < 0 or ray >= len(samples) or (kind and not kind & HIT_EXIT):
            continue
        point = samples[ray][0]
        distance = math.dist(point, values[start + 3 : start + 6])
        if distance <= 2 * _START_INSIDE_M:
            continue  # the ray's own face
        if ray not in found or distance < found[ray]:
            found[ray] = distance
    return found


def summarize(
    samples: list[tuple[list[float], list[float]]],
    distances: dict[int, float],
    min_wall_mm: float,
) -> dict[str, Any]:
    """The check's reply: the thinnest wall, where it is, and what is too thin.

    Args:
        samples: The ``(point, normal)`` pairs, metres.
        distances: :func:`exit_distances`.
        min_wall_mm: The thinnest wall the printer can make.

    Returns:
        dict[str, Any]: ``min_thickness_mm``, ``at_mm`` and ``normal`` of the
        thinnest sample, ``samples``, ``measured``, ``below_minimum`` (count),
        ``thin_spots`` (the thinnest, up to 20), ``min_wall_mm`` and ``ok``.
    """
    measured = sorted(distances.items(), key=lambda item: item[1])
    reply: dict[str, Any] = {
        "samples": len(samples),
        "measured": len(measured),
        "min_wall_mm": min_wall_mm,
        "min_thickness_mm": None,
        "below_minimum": 0,
        "thin_spots": [],
        "ok": None,
    }
    if not measured:
        return reply

    def _spot(ray: int, distance: float) -> dict[str, Any]:
        point, normal = samples[ray]
        return {
            "thickness_mm": round(distance * 1000, 4),
            "at_mm": [round(c * 1000, 3) for c in point],
            "normal": [round(c, 4) + 0.0 for c in normal],
        }

    thinnest = _spot(*measured[0])
    below = [(r, d) for r, d in measured if d * 1000 < min_wall_mm]
    reply.update(
        {
            "min_thickness_mm": thinnest["thickness_mm"],
            "at_mm": thinnest["at_mm"],
            "normal": thinnest["normal"],
            "below_minimum": len(below),
            "thin_spots": [_spot(r, d) for r, d in below[:MAX_THIN_SPOTS]],
            "ok": not below,
        }
    )
    return reply


def measure_wall_thickness(
    adapter: Any, min_wall_mm: float, max_rays: int = MAX_RAYS
) -> dict[str, Any]:
    """Cast the rays on the active part and summarize the wall thickness.

    Args:
        adapter: A connected adapter with a part as ``currentModel``.
        min_wall_mm: The thinnest wall the printer can make.
        max_rays: The most rays to cast.

    Returns:
        dict[str, Any]: :func:`summarize`'s reply plus ``bodies`` and ``faces``.

    Raises:
        LookupError: The part has no solid body, or no face could be sampled.
        RuntimeError: ``RayIntersections`` found nothing at all.
    """
    # io's pythoncom is a stand-in without pywin32, and _variant_array then
    # passes plain lists through.
    from .io import _variant_array, pythoncom

    vt_dispatch = getattr(pythoncom, "VT_DISPATCH", 9)
    vt_r8 = getattr(pythoncom, "VT_R8", 5)

    model = adapter.currentModel
    _flag(adapter, model, "GetBodies2", "GetRayIntersectionsPoints")
    bodies = as_list(_attempt(adapter, lambda: model.GetBodies2(0, True)))
    if not bodies:
        raise LookupError("The active part has no solid body to measure.")
    samples: list[tuple[list[float], list[float]]] = []
    face_count = 0
    for body in bodies:
        _flag(adapter, body, "GetFaces")
        for face in as_list(_attempt(adapter, lambda b=body: b.GetFaces())):
            limits.check("sampling faces")
            face_count += 1
            _flag(adapter, face, "GetTessTriangles", "GetTessNorms")
            samples += sample_points(
                _attempt(adapter, lambda f=face: f.GetTessTriangles(True)),
                _attempt(adapter, lambda f=face: f.GetTessNorms()),
            )
    if not samples:
        raise LookupError(
            "No face of the part could be sampled (SolidWorks gave no "
            "tessellation; show the part in the graphics area and retry)."
        )
    samples = thin_out(samples, max_rays)
    starts, directions = ray_arrays(samples)

    extension = model.Extension
    _flag(adapter, extension, "RayIntersections")
    count = extension.RayIntersections(
        _variant_array(vt_dispatch, bodies),
        _variant_array(vt_r8, starts),
        _variant_array(vt_r8, directions),
        RAY_ENTRY_EXIT,
        _HIT_RADIUS_M,
        0.0,
        True,
    )
    if not count:
        raise RuntimeError(
            f"RayIntersections found no hit for {len(samples)} rays cast into "
            "the part, so no thickness could be measured."
        )
    hits = model.GetRayIntersectionsPoints()
    reply = summarize(samples, exit_distances(hits, samples), min_wall_mm)
    reply.update({"bodies": len(bodies), "faces": face_count})
    return reply
