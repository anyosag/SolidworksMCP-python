"""A blind cut's floor area, and the warning for a cut whose depth was mostly air."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import cut_check

# Sketch on Top: x = +X, y = -Z, normal = +Y (inverse ArrayData rows).
_TOP = [1, 0, 0, 0, 0, -1, 0, 1, 0, 0, 0.005, 0, 1, 0, 0, 0]


class _Adapter:
    def _attempt(self, callback: Any, default: Any = None) -> Any:
        try:
            return callback()
        except Exception:
            return default


def _sketch_feature(data: Any = _TOP) -> Any:
    inverse = SimpleNamespace(ArrayData=data)
    transform = SimpleNamespace(Inverse=lambda: inverse)
    sketch = SimpleNamespace(ModelToSketchTransform=transform)
    return SimpleNamespace(GetSpecificFeature2=lambda: sketch)


def _face(normal: list[float], area_m2: float) -> Any:
    return SimpleNamespace(Normal=normal, GetArea=lambda: area_m2)


def _cut(*faces: Any) -> Any:
    return SimpleNamespace(GetFaces=lambda: list(faces))


def test_the_floor_is_the_faces_facing_along_the_sketch_normal() -> None:
    cut = _cut(
        _face([0, 1, 0], 1e-4),  # floor: 100 mm²
        _face([0, -1, 0], 2e-5),  # a step facing the other way: 20 mm²
        _face([1, 0, 0], 5e-5),  # wall
        _face([0, 0, 0], 3e-5),  # cylinder wall (not planar)
        _face([0.01, 0.9999, 0], 1e-6),  # within 2.5 degrees
    )

    assert cut_check.measure_floor(_Adapter(), cut, _sketch_feature()) == (
        pytest.approx(121.0)
    )


def test_a_cut_without_a_floor_has_no_area() -> None:
    cut = _cut(_face([1, 0, 0], 5e-5), _face([0, 0, 0], 3e-5))

    assert cut_check.measure_floor(_Adapter(), cut, _sketch_feature()) is None
    assert (
        cut_check.measure_floor(_Adapter(), _cut(_face([], 1.0)), _sketch_feature())
        is None
    )


@pytest.mark.parametrize(
    "feature",
    [
        _sketch_feature(data=[1, 2, 3]),
        SimpleNamespace(GetSpecificFeature2=lambda: SimpleNamespace()),
    ],
)
def test_an_unreadable_sketch_gives_no_area(feature: Any) -> None:
    cut = _cut(_face([0, 1, 0], 1e-4))

    assert cut_check.measure_floor(_Adapter(), cut, feature) is None


def test_a_cut_that_removed_far_less_is_named() -> None:
    warning = cut_check.shortfall_warning(1.13, 4.525, 2.0)

    assert warning is not None
    assert warning.startswith("The cut removed 1.13 mm³, far less than its floor")
    assert "4.525 mm² x 2 mm = 9.05 mm³" in warning


@pytest.mark.parametrize(
    ("removed", "floor", "depth"),
    [
        (9.05, 4.525, 2.0),  # all of it
        (5.0, 4.525, 2.0),  # over half
        (None, 4.525, 2.0),
        (1.0, None, 2.0),
        (1.0, 4.525, 0.0),
    ],
)
def test_otherwise_nothing_is_said(
    removed: float | None, floor: float | None, depth: float
) -> None:
    assert cut_check.shortfall_warning(removed, floor, depth) is None
