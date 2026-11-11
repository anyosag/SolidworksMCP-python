"""``get_dimension`` and ``set_dimension`` use the dimension's own unit.

From the Cellvis dish rack: ``set_dimension`` took every value as millimetres,
so a circular pattern's instance count of 2 was written as 0.002 and its
180-degree spacing as 0.18 rad, and the pattern failed to rebuild. The unit
now follows ``IDimension.GetType()``: mm for a length, degrees for an angle,
the number itself for a count.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import io
from solidworks_mcp.adapters.solidworks.io import SolidWorksIOMixin

LENGTH, ANGLE, COUNT = 0, 1, 2


class _Dimension:
    """An ``IDimension`` whose ``SystemValue`` SolidWorks may refuse to change."""

    def __init__(self, kind: int | None, system_value: float, keeps: bool = False):
        self.kind = kind
        self._value = system_value
        self.keeps = keeps
        self.written: list[float] = []

    def GetType(self) -> int:  # noqa: N802 - COM name
        if self.kind is None:
            raise AttributeError("GetType")
        return self.kind

    @property
    def SystemValue(self) -> float:  # noqa: N802 - COM name
        return self._value

    @SystemValue.setter
    def SystemValue(self, value: float) -> None:  # noqa: N802 - COM name
        self.written.append(value)
        if not self.keeps:
            self._value = value


class _Model:
    def __init__(self, dimension: Any) -> None:
        self.dimension = dimension
        self.rebuilds = 0

    def Parameter(self, _name: str) -> Any:  # noqa: N802 - COM name
        return self.dimension

    def EditRebuild3(self) -> bool:  # noqa: N802 - COM name
        self.rebuilds += 1
        return True


class _Harness(SolidWorksIOMixin):
    def __init__(self, dimension: Any) -> None:
        self.currentModel = _Model(dimension)

    def _attempt(self, callback: Any, default: Any = None) -> Any:
        try:
            return callback()
        except Exception:
            return default

    def _handle_com_operation(self, _name: str, callback: Any) -> AdapterResult[Any]:
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))


@pytest.mark.parametrize(
    ("kind", "system_value", "expected"),
    [
        (LENGTH, 0.015, {"value": 15.0, "units": "mm", "kind": "length"}),
        (ANGLE, math.pi, {"value": 180.0, "units": "deg", "kind": "angle"}),
        (COUNT, 6.0, {"value": 6.0, "units": "count", "kind": "count"}),
        (7, 0.002, {"value": 2.0, "units": "mm", "kind": "length"}),
        (None, 0.002, {"value": 2.0, "units": "mm", "kind": "length"}),
    ],
)
async def test_a_dimension_is_read_in_its_own_unit(
    kind: int | None, system_value: float, expected: dict[str, Any]
) -> None:
    result = await _Harness(_Dimension(kind, system_value)).get_dimension("D1@X")

    assert result.is_success, result.error
    assert result.data == expected


@pytest.mark.parametrize(
    ("kind", "before", "value", "written", "reply"),
    [
        (COUNT, 6.0, 2, 2.0, (6.0, 2.0, "count", "count")),
        (ANGLE, math.pi / 3, 180, math.pi, (60.0, 180.0, "deg", "angle")),
        (LENGTH, 0.015, 20, 0.02, (15.0, 20.0, "mm", "length")),
    ],
)
async def test_a_dimension_is_written_in_its_own_unit(
    kind: int, before: float, value: float, written: float, reply: tuple
) -> None:
    dimension = _Dimension(kind, before)

    result = await _Harness(dimension).set_dimension("D1@CirPattern1", value)

    assert result.is_success, result.error
    assert dimension.written == [pytest.approx(written)]
    data = result.data or {}
    assert (data["old_value"], data["new_value"], data["units"], data["kind"]) == (
        pytest.approx(reply[0]),
        pytest.approx(reply[1]),
        reply[2],
        reply[3],
    )


async def test_a_count_must_be_a_whole_number() -> None:
    dimension = _Dimension(COUNT, 6.0)
    harness = _Harness(dimension)

    result = await harness.set_dimension("D1@CirPattern1", 2.5)

    assert result.is_error
    assert "'D1@CirPattern1' is a count" in (result.error or "")
    assert "not 2.5" in (result.error or "")
    assert dimension.written == []
    assert harness.currentModel.rebuilds == 0


async def test_a_value_solidworks_does_not_take_is_an_error() -> None:
    """A driven dimension, or one an equation sets, keeps its value."""
    dimension = _Dimension(ANGLE, math.pi / 2, keeps=True)

    result = await _Harness(dimension).set_dimension("D2@CirPattern1", 180)

    assert result.is_error
    assert "SolidWorks kept dimension 'D2@CirPattern1' at 90 deg, not 180" in (
        result.error or ""
    )


class _Unreadable:
    """A dimension whose value can be written but not read back."""

    def __init__(self) -> None:
        self.written: list[float] = []

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "SystemValue":
            self.written.append(value)
        object.__setattr__(self, name, value)

    def __getattribute__(self, name: str) -> Any:
        if name == "SystemValue":
            raise AttributeError(name)
        return object.__getattribute__(self, name)


async def test_a_value_that_cannot_be_read_back_reports_what_was_written() -> None:
    dimension = _Unreadable()

    result = await _Harness(dimension).set_dimension("D1@Sketch1", 12.5)

    assert result.is_success, result.error
    assert dimension.written == [pytest.approx(0.0125)]
    assert result.data == {
        "old_value": None,
        "new_value": pytest.approx(12.5),
        "units": "mm",
        "kind": "length",
    }


def test_system_values_in_the_tools_units() -> None:
    assert io.from_system_value(2.0000000001, "count", 1.0) == 2.0
    assert io.from_system_value(math.pi / 4, "angle", math.pi / 180) == 45.0
    assert io.from_system_value(0.0254, "length", 0.001) == 25.4
