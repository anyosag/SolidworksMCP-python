"""A zoom box in model coordinates, turned into the view's (``zoom_box``)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import zoom_box

#: The Cellvis right-view box, around the +X block's face (model mm).
RIGHT_BOX = [29, -2, -11, 31, 22, 11]


def right_view(p: Sequence[float]) -> list[float]:
    """The right view: screen right is model -Z, up is Y, out of the screen X."""
    return [-p[2], p[1], p[0]]


class _Point:
    def __init__(self, data: Any) -> None:
        self.ArrayData = tuple(getattr(data, "value", data))

    def MultiplyTransform(self, orientation: Any) -> Any:  # noqa: N802
        return _Point(orientation(self.ArrayData))


class _Adapter:
    def __init__(self, utility: Any = None) -> None:
        self.swApp = SimpleNamespace(GetMathUtility=lambda: utility)

    def _attempt(self, fn: Any, default: Any = None) -> Any:
        try:
            return fn()
        except Exception:
            return default


def _doc(orientation: Callable[[Sequence[float]], list[float]] | None) -> Any:
    view = None if orientation is None else SimpleNamespace(Orientation3=orientation)
    return SimpleNamespace(ActiveView=view)


_UTILITY = SimpleNamespace(CreatePoint=_Point)


def test_a_box_has_eight_corners_in_metres() -> None:
    corners = zoom_box.corners_m([0, 0, 0, 20, 10, 5])

    assert len(set(corners)) == 8
    assert zoom_box.bounds(corners) == (0.0, 0.0, 0.0, 0.02, 0.01, 0.005)


def test_in_the_right_view_model_x_and_z_swap() -> None:
    """What the Cellvis session found by hand: [-11,-2,29, 11,22,31] worked."""
    viewed = zoom_box.in_view(_Adapter(_UTILITY), _doc(right_view), RIGHT_BOX)

    assert viewed == pytest.approx((-0.011, -0.002, 0.029, 0.011, 0.022, 0.031))


def test_in_the_front_view_the_box_is_as_given() -> None:
    viewed = zoom_box.in_view(_Adapter(_UTILITY), _doc(list), [0, 0, 0, 20, 10, 5])

    assert viewed == pytest.approx((0.0, 0.0, 0.0, 0.02, 0.01, 0.005))


@pytest.mark.parametrize(
    ("adapter", "doc"),
    [
        (_Adapter(_UTILITY), _doc(None)),
        (_Adapter(None), _doc(right_view)),
        (
            _Adapter(SimpleNamespace(CreatePoint=lambda _d: _Point([]))),
            _doc(lambda _p: []),
        ),
    ],
    ids=["no view", "no math utility", "an unreadable point"],
)
def test_without_the_views_orientation_there_is_no_view_box(
    adapter: Any, doc: Any
) -> None:
    assert zoom_box.in_view(adapter, doc, RIGHT_BOX) is None
