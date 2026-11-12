"""Moving an inserted component's origin to the asked point (``placement``)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import placement

_IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def _data(x: float, y: float, z: float) -> list[float]:
    return [*_IDENTITY, x, y, z, 1.0, 0.0, 0.0, 0.0]


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


def _place(component: _Component, model: _Model | None = None) -> dict[str, Any]:
    return placement.place_origin(
        _Adapter(), model or _Model(), _Assembly(component), component, (0.0, 0.0, 0.01)
    )


def test_a_transform_gets_the_new_origin_and_keeps_its_rotation() -> None:
    turned = [0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1, 2, 3, 1, 0, 0, 0]

    moved = placement.translated(turned, (0.1, 0.2, 0.3))

    assert moved[:9] == turned[:9]
    assert moved[9:12] == [0.1, 0.2, 0.3]
    assert moved[12:] == [1.0, 0.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="16 values, not 3"):
        placement.translated([1, 2, 3], (0, 0, 0))


def test_a_transform_reads_as_origin_in_mm_and_rotation_rows() -> None:
    assert placement.describe(_data(0.0, -0.00675, 0.0037)) == {
        "origin_mm": [0.0, -6.75, 3.7],
        "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    }


def test_a_component_off_its_origin_is_moved_there() -> None:
    """The Cellvis base: inserted at (0, 0, 10) mm, its centre landed there."""
    component = _Component(_data(0.0, -0.00675, 0.0137))
    model = _Model()

    reply = _place(component, model)

    assert reply == {
        "placed": True,
        "moved": True,
        "origin_mm": [0.0, 0.0, 10.0],
        "rotation": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    }
    assert component.calls == ["Transform2"]
    assert model.calls == ["rebuild"]


def test_a_fixed_component_is_floated_for_the_move_and_fixed_again() -> None:
    component = _Component(_data(0.0, 0.0, 0.0), fixed=True)

    reply = _place(component)

    assert reply["placed"] is True
    assert component.calls == ["Select4", "unfix", "Transform2", "Select4", "fix"]
    assert component.fixed is True


def test_a_component_already_at_its_origin_is_left_alone() -> None:
    component = _Component(_data(0.0, 0.0, 0.01))

    reply = _place(component)

    assert (reply["placed"], reply["moved"]) == (True, False)
    assert component.calls == []


def test_a_move_solidworks_ignores_is_reported() -> None:
    component = _Component(_data(0.0, -0.00675, 0.0137), sticks=False)

    reply = _place(component)

    assert (reply["placed"], reply["moved"]) == (False, True)
    assert reply["origin_mm"] == [0.0, -6.75, 13.7]


def test_an_unreadable_transform_is_not_a_placement() -> None:
    assert _place(_Component(None)) == {"placed": False, "moved": False}
