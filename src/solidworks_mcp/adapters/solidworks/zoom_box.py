"""A zoom box given in model coordinates, as ``ViewZoomTo2`` takes it.

``IModelDoc2.ViewZoomTo2`` takes its two corners in the view's coordinates,
not the model's: the SolidWorks "Zoom to Region" example transforms each
point by the view's orientation (``IModelView.Orientation3``) first. In the
front view the two are the same, so a box zoomed right there; in the right
view the Cellvis DishRack box around the +X block zoomed onto the back
block, and only a box with model X and Z swapped zoomed where meant
(2026-11-12). So the box's eight corners are transformed by the view's
orientation (``IMathPoint.MultiplyTransform``) and the box around them is
what is zoomed to.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import product
from typing import Any

from .com_utils import attempt as _attempt
from .com_utils import double_array as _double_array


def corners_m(box_mm: Sequence[float]) -> list[tuple[float, float, float]]:
    """The eight corners of a box ``[x1, y1, z1, x2, y2, z2]`` mm, in metres."""
    low, high = box_mm[:3], box_mm[3:]
    return [
        (float(x) / 1000.0, float(y) / 1000.0, float(z) / 1000.0)
        for x, y, z in product(*zip(low, high, strict=True))
    ]


def bounds(points: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """The lowest and highest corner of the box around ``points``."""
    low = tuple(min(p[axis] for p in points) for axis in range(3))
    high = tuple(max(p[axis] for p in points) for axis in range(3))
    return (*low, *high)


def in_view(
    adapter: Any, doc: Any, box_mm: Sequence[float]
) -> tuple[float, ...] | None:
    """``ViewZoomTo2``'s six arguments for a box in model mm, or None.

    Returns:
        tuple[float, ...] | None: The box around the corners in the active
        view's coordinates (metres), or None when the view's orientation or
        the math utility can't be read.
    """
    view = _attempt(adapter, lambda: doc.ActiveView)
    orientation = _attempt(adapter, lambda: view.Orientation3) if view else None
    utility = _attempt(adapter, lambda: adapter.swApp.GetMathUtility())
    if orientation is None or utility is None:
        return None
    points = []
    for corner in corners_m(box_mm):
        point = utility.CreatePoint(_double_array(list(corner)))
        moved = point.MultiplyTransform(orientation)
        data = _attempt(adapter, lambda m=moved: m.ArrayData)
        if not isinstance(data, (list, tuple)) or len(data) < 3:
            return None
        points.append([float(v) for v in data[:3]])
    return bounds(points)
