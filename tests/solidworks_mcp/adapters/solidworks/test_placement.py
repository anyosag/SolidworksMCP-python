"""Placing a component: origin, rotation and fixed state (``placement``)."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import placement

_IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
_ROWS = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
#: A quarter turn about Y: the component's X axis points along -Z.
_QUARTER_Y = [[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]


def _data(
    x: float, y: float, z: float, rotation: list[float] = _IDENTITY
) -> list[float]:
    return [*rotation, x, y, z, 1.0, 0.0, 0.0, 0.0]


class _Transform:
    def __init__(self, data: Any) -> None:
        self.ArrayData = tuple(getattr(data, "value", data))


class _Component:
    """``IComponent2`` whose box centre SolidWorks put at the asked point."""

    def __init__(
        self, data: list[float] | None, fixed: bool = False, sticks: bool = True
    ):
        self._transform = None if data is None else _Transform(data)
        self.fixed, self._sticks = fixed, sticks
        self.calls: list[str] = []

    @property
    def Transform2(self) -> Any:  # noqa: N802
        return self._transform

    @Transform2.setter
    def Transform2(self, value: Any) -> None:  # noqa: N802
        self.calls.append("Transform2")
        if self._sticks:
            self._transform = value

    def IsFixed(self) -> bool:  # noqa: N802
        return self.fixed

    def Select4(self, append: bool, data: Any, mark: bool) -> bool:  # noqa: N802
        self.calls.append("Select4")
        return True


class _Assembly:
    def __init__(self, component: _Component) -> None:
        self._component = component

    def FixComponent(self) -> None:  # noqa: N802
        self._component.calls.append("fix")
        self._component.fixed = True

    def UnfixComponent(self) -> None:  # noqa: N802
        self._component.calls.append("unfix")
        self._component.fixed = False


class _Model:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.SelectionManager = SimpleNamespace(CreateSelectData=lambda: "data")

    def ClearSelection2(self, _all: bool) -> None:  # noqa: N802
        self.calls.append("clear")

    def EditRebuild3(self) -> bool:  # noqa: N802
        self.calls.append("rebuild")
        return True


class _Adapter:
    def __init__(self) -> None:
        self.swApp = SimpleNamespace(
            GetMathUtility=lambda: SimpleNamespace(CreateTransform=_Transform)
        )

    def _attempt(self, fn: Any, default: Any = None) -> Any:
        try:
            return fn()
        except Exception:
            return default


def _place(
    component: _Component,
    model: _Model | None = None,
    rows: Any = None,
    fixed: bool | None = None,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.01),
) -> dict[str, Any]:
    return placement.place(
        _Adapter(),
        model or _Model(),
        _Assembly(component),
        component,
        origin,
        rows,
        fixed,
    )


# ---- rotations ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("degrees", "rows"),
    [
        ((0, 0, 0), _ROWS),
        ((0, 90, 0), _QUARTER_Y),
        ((90, 0, 0), [[1, 0, 0], [0, 0, 1], [0, -1, 0]]),
        ((0, 0, 90), [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]),
        # X first, then Z: x stays x, then goes to y.
        ((90, 0, 90), [[0, 1, 0], [0, 0, 1], [1, 0, 0]]),
    ],
)
def test_turns_about_x_then_y_then_z_by_the_right_hand_rule(degrees, rows) -> None:
    got = placement.rotation_rows_from_deg(*degrees)

    flat = [x for row in got for x in row]
    assert flat == pytest.approx([x for row in rows for x in row], abs=1e-12)


@pytest.mark.parametrize(
    ("rows", "fragment"),
    [
        ([[1, 0, 0], [0, 1, 0]], "three rows of three"),
        ([[1, 0], [0, 1], [0, 0]], "three rows of three"),
        ([[2, 0, 0], [0, 1, 0], [0, 0, 1]], "unit vectors at right angles"),
        ([[1, 0, 0], [1, 0, 0], [0, 0, 1]], "unit vectors at right angles"),
        ([[1, 0, 0], [0, 1, 0], [0, 0, -1]], "mirror"),
    ],
)
def test_a_matrix_that_is_not_a_rotation_is_named(rows, fragment) -> None:
    assert fragment in (placement.rotation_problem(rows) or "")


def test_a_turned_matrix_is_a_rotation() -> None:
    c, s = math.cos(0.3), math.sin(0.3)
    assert placement.rotation_problem([[c, s, 0], [-s, c, 0], [0, 0, 1]]) is None


# ---- transforms --------------------------------------------------------------


def test_a_transform_gets_the_new_origin_and_keeps_its_rotation() -> None:
    turned = [0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1, 2, 3, 1, 0, 0, 0]

    moved = placement.transformed(turned, (0.1, 0.2, 0.3))
    rotated = placement.transformed(turned, (0.1, 0.2, 0.3), _QUARTER_Y)

    assert moved[:9] == turned[:9]
    assert moved[9:12] == [0.1, 0.2, 0.3]
    assert moved[12:] == [1.0, 0.0, 0.0, 0.0]
    assert rotated[:9] == [0.0, 0.0, -1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="16 values, not 3"):
        placement.transformed([1, 2, 3], (0, 0, 0))


def test_a_transform_reads_as_origin_in_mm_and_rotation_rows() -> None:
    assert placement.describe(_data(0.0, -0.00675, 0.0037)) == {
        "origin_mm": [0.0, -6.75, 3.7],
        "rotation": _ROWS,
    }


# ---- placing -------------------------------------------------------------------


def test_a_component_off_its_origin_is_moved_there() -> None:
    """The Cellvis base: inserted at (0, 0, 10) mm, its centre landed there."""
    component = _Component(_data(0.0, -0.00675, 0.0137))
    model = _Model()

    reply = placement.place_origin(
        _Adapter(), model, _Assembly(component), component, (0.0, 0.0, 0.01)
    )

    assert reply == {
        "placed": True,
        "moved": True,
        "fixed": False,
        "origin_mm": [0.0, 0.0, 10.0],
        "rotation": _ROWS,
    }
    assert component.calls == ["Transform2"]
    assert model.calls == ["rebuild"]


def test_a_component_is_turned_as_asked() -> None:
    component = _Component(_data(0.0, 0.0, 0.0))

    reply = _place(component, rows=_QUARTER_Y, origin=(0.01, 0.02, 0.03))

    assert reply["placed"] is True
    assert reply["origin_mm"] == [10.0, 20.0, 30.0]
    assert reply["rotation"][0] == [0.0, 0.0, -1.0]


def test_a_fixed_component_is_floated_for_the_move_and_fixed_again() -> None:
    component = _Component(_data(0.0, 0.0, 0.0), fixed=True)

    reply = _place(component)

    assert (reply["placed"], reply["fixed"]) == (True, True)
    assert component.calls == ["Select4", "unfix", "Transform2", "Select4", "fix"]


@pytest.mark.parametrize(
    ("was_fixed", "fixed", "calls"),
    [
        (True, False, ["Select4", "unfix", "Transform2"]),
        (False, True, ["Transform2", "Select4", "fix"]),
    ],
)
def test_a_moved_component_ends_fixed_or_floating_as_asked(
    was_fixed: bool, fixed: bool, calls: list[str]
) -> None:
    component = _Component(_data(0.0, 0.0, 0.0), fixed=was_fixed)

    reply = _place(component, fixed=fixed)

    assert reply["fixed"] is fixed
    assert component.calls == calls


@pytest.mark.parametrize("fixed", [None, False])
def test_a_component_already_in_place_is_left_alone(fixed: bool | None) -> None:
    component = _Component(_data(0.0, 0.0, 0.01))

    reply = _place(component, fixed=fixed)

    assert (reply["placed"], reply["moved"], reply["fixed"]) == (True, False, False)
    assert component.calls == []


def test_a_component_in_place_can_still_be_fixed() -> None:
    component = _Component(_data(0.0, 0.0, 0.01))

    reply = _place(component, fixed=True)

    assert (reply["moved"], reply["fixed"]) == (False, True)
    assert component.calls == ["Select4", "fix"]


def test_a_rotation_that_differs_is_a_move() -> None:
    component = _Component(_data(0.0, 0.0, 0.01))

    reply = _place(component, rows=_QUARTER_Y)

    assert (reply["placed"], reply["moved"]) == (True, True)


def test_a_move_solidworks_ignores_is_reported() -> None:
    component = _Component(_data(0.0, -0.00675, 0.0137), sticks=False)

    reply = _place(component)

    assert (reply["placed"], reply["moved"]) == (False, True)
    assert reply["origin_mm"] == [0.0, -6.75, 13.7]


def test_a_turn_solidworks_ignores_is_reported() -> None:
    component = _Component(_data(0.0, 0.0, 0.01), sticks=False)

    reply = _place(component, rows=_QUARTER_Y)

    assert reply["placed"] is False
    assert reply["rotation"] == _ROWS


def test_an_unreadable_transform_is_not_a_placement() -> None:
    assert _place(_Component(None)) == {"placed": False, "moved": False}
