"""Whether a blind cut went into the material: its floor area times its depth.

From the Cellvis dish rack: a cut sketched on an offset plane removed a
1.13 mm³ sliver where 9.05 mm³ was meant, and reported success. Most of its
depth was in air above the part. A blind cut's floor (its planar faces facing
along the sketch normal) has the profile's area wherever the cut reached
material, so floor area times depth is what it should remove; far less means
the depth ran outside the part.
"""

from __future__ import annotations

import math
from typing import Any

from .com_utils import as_list
from .com_utils import attempt as _attempt
from .com_utils import flag as _flag
from .sketch import axes_from_transform

#: A cut that removed less than this share of floor area x depth is reported.
SHORTFALL = 0.5
#: |cos| above which a face faces along the sketch normal (about 2.5 degrees).
_PARALLEL = 0.999


def sketch_normal(adapter: Any, sketch_feature: Any) -> list[float] | None:
    """The normal of a sketch feature's plane, in model coordinates."""
    _flag(adapter, sketch_feature, "GetSpecificFeature2")
    sketch = _attempt(adapter, lambda: sketch_feature.GetSpecificFeature2())
    transform = _attempt(adapter, lambda: sketch.ModelToSketchTransform)
    if transform is None:
        return None
    _flag(adapter, transform, "Inverse")
    inverse = _attempt(adapter, lambda: transform.Inverse())
    axes = axes_from_transform(_attempt(adapter, lambda: inverse.ArrayData))
    return None if axes is None else [float(c) for c in axes["normal"]]


def floor_area_mm2(adapter: Any, feature: Any, normal: list[float]) -> float | None:
    """The total area of the cut's faces that face along ``normal``, mm².

    Args:
        adapter: The adapter (for ``_attempt``).
        feature: The cut's ``IFeature``.
        normal: The sketch normal (a unit vector).

    Returns:
        float | None: The area, or None when the cut has no such face (it
        went through) or its faces can't be read.
    """
    _flag(adapter, feature, "GetFaces")
    area = 0.0
    found = False
    for face in as_list(_attempt(adapter, lambda: feature.GetFaces())):
        _flag(adapter, face, "GetArea")
        facing = [float(c) for c in (_attempt(adapter, lambda f=face: f.Normal) or [])]
        length = math.sqrt(sum(c * c for c in facing[:3]))
        if len(facing) < 3 or length == 0.0:
            continue  # not planar: IFace2.Normal is [0, 0, 0]
        cos = sum(a * b for a, b in zip(facing[:3], normal, strict=True)) / length
        if abs(cos) > _PARALLEL:
            area += float(_attempt(adapter, lambda f=face: f.GetArea()) or 0.0)
            found = True
    return area * 1e6 if found else None


def measure_floor(adapter: Any, feature: Any, sketch_feature: Any) -> float | None:
    """The cut's floor area in mm², or None when it can't be told."""
    normal = sketch_normal(adapter, sketch_feature)
    return None if normal is None else floor_area_mm2(adapter, feature, normal)


def shortfall_warning(
    removed_mm3: float | None, floor_mm2: float | None, depth_mm: float
) -> str | None:
    """A warning when a blind cut removed far less than floor area x depth.

    Args:
        removed_mm3: The volume the cut removed (positive), if measured.
        floor_mm2: The cut's floor area, if measured.
        depth_mm: The cut's depth.

    Returns:
        str | None: The warning, or None when the cut removed about what it
        should, or either number is missing.
    """
    if removed_mm3 is None or not floor_mm2 or depth_mm <= 0:
        return None
    expected = floor_mm2 * depth_mm
    if removed_mm3 >= SHORTFALL * expected:
        return None
    return (
        f"The cut removed {removed_mm3:.4g} mm³, far less than its floor area "
        f"times its depth ({floor_mm2:.4g} mm² x {depth_mm:g} mm = "
        f"{expected:.4g} mm³): most of its depth is outside the part. Check "
        "the sketch plane and the cut direction, or use end_condition "
        "'UpToNext' or 'ThroughAll'."
    )
