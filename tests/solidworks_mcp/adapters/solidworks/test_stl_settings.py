"""STL mesh settings for one export, put back afterwards (``stl_settings``)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import stl_settings as stl


class _App:
    """``ISldWorks`` user preferences; ``refuse`` ids keep their old value."""

    def __init__(self, refuse: set[int] | None = None, broken: set[int] | None = None):
        self.values: dict[tuple[str, int], Any] = {
            ("integer", stl.STL_QUALITY): 2,
            ("double", stl.STL_DEVIATION): 0.0005,
            ("double", stl.STL_ANGLE_TOLERANCE): 0.17,
            ("integer", stl.STL_UNITS): 3,
            ("toggle", stl.STL_BINARY): True,
        }
        self.refuse = refuse or set()
        self.broken = broken or set()
        self.writes: list[tuple[int, Any]] = []

    def _set(self, kind: str, pref: int, value: Any) -> bool:
        self.writes.append((pref, value))
        if pref in self.broken and len(self.writes) > 1:
            raise RuntimeError("RPC server is unavailable")
        if pref not in self.refuse:
            self.values[(kind, pref)] = value
        return True

    def GetUserPreferenceIntegerValue(self, pref: int) -> int:  # noqa: N802
        return self.values[("integer", pref)]

    def SetUserPreferenceIntegerValue(self, pref: int, value: int) -> bool:  # noqa: N802
        return self._set("integer", pref, value)

    def GetUserPreferenceDoubleValue(self, pref: int) -> float:  # noqa: N802
        return self.values[("double", pref)]

    def SetUserPreferenceDoubleValue(self, pref: int, value: float) -> bool:  # noqa: N802
        return self._set("double", pref, value)

    def GetUserPreferenceToggle(self, pref: int) -> bool:  # noqa: N802
        return self.values[("toggle", pref)]

    def SetUserPreferenceToggle(self, pref: int, value: bool) -> bool:  # noqa: N802
        return self._set("toggle", pref, value)


def test_a_deviation_and_angle_make_the_resolution_custom() -> None:
    changes = stl.preference_changes(
        {"deviation_mm": 0.01, "angle_deg": 5, "units": "mm", "binary": False}
    )

    assert [(kind, pref) for kind, pref, _v, _l in changes] == [
        ("integer", stl.STL_QUALITY),
        ("double", stl.STL_DEVIATION),
        ("double", stl.STL_ANGLE_TOLERANCE),
        ("integer", stl.STL_UNITS),
        ("toggle", stl.STL_BINARY),
    ]
    values = [value for _k, _p, value, _l in changes]
    assert values[0] == 3
    assert values[1] == pytest.approx(1e-5)
    assert values[2] == pytest.approx(math.radians(5))
    assert values[3:] == [0, False]
    assert [label for *_rest, label in changes] == [
        "resolution custom",
        "deviation 0.01 mm",
        "angle 5 deg",
        "units mm",
        "ASCII",
    ]


def test_only_what_is_given_is_changed() -> None:
    assert stl.preference_changes({}) == []
    assert stl.preference_changes({"resolution": "fine"}) == [
        ("integer", stl.STL_QUALITY, 2, "resolution fine")
    ]
    assert stl.preference_changes({"binary": True})[0][3] == "binary"


@pytest.mark.parametrize(
    ("settings", "fragment"),
    [
        ({"resolution": "coarse", "deviation_mm": 0.1}, "deviation_mm need"),
        ({"resolution": "fine", "angle_deg": 3}, "angle_deg need resolution 'custom'"),
        ({"resolution": "silky"}, "Unknown STL resolution 'silky'"),
        ({"units": "furlong"}, "Unknown STL units 'furlong'"),
    ],
)
def test_impossible_settings_are_refused(
    settings: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(ValueError, match=None) as caught:
        stl.preference_changes(settings)
    assert fragment in str(caught.value)


@pytest.mark.parametrize(
    ("kind", "wanted", "read", "same"),
    [
        ("double", 1e-5, 1.0000001e-5, True),
        ("double", 1e-5, 2e-5, False),
        ("toggle", True, 1, True),
        ("integer", 3, 3.0, True),
        ("integer", 3, None, False),
    ],
)
def test_a_value_read_back(kind: str, wanted: Any, read: Any, same: bool) -> None:
    assert stl.same_value(kind, wanted, read) is same


def test_the_users_values_are_read_set_and_put_back() -> None:
    app = _App()
    changes = stl.preference_changes({"deviation_mm": 0.01, "units": "mm"})

    previous = stl.apply_changes(app, changes)

    assert app.values[("integer", stl.STL_QUALITY)] == 3
    assert app.values[("integer", stl.STL_UNITS)] == 0
    assert stl.restore(app, previous) == []
    assert app.values[("integer", stl.STL_QUALITY)] == 2
    assert app.values[("double", stl.STL_DEVIATION)] == 0.0005
    assert app.values[("integer", stl.STL_UNITS)] == 3


def test_a_setting_solidworks_refuses_puts_the_others_back() -> None:
    app = _App(refuse={stl.STL_UNITS})
    changes = stl.preference_changes({"resolution": "fine", "units": "m"})

    with pytest.raises(RuntimeError) as caught:
        stl.apply_changes(app, changes)

    assert str(caught.value) == (
        "SolidWorks did not take the STL setting units m, so nothing was "
        "exported; your STL options are as they were."
    )
    assert app.values[("integer", stl.STL_QUALITY)] == 2


def test_a_setting_that_cannot_be_put_back_is_counted() -> None:
    app = _App(refuse={stl.STL_UNITS}, broken={stl.STL_QUALITY})
    changes = stl.preference_changes({"resolution": "fine", "units": "m"})

    with pytest.raises(RuntimeError, match="1 setting\\(s\\) could not be put back"):
        stl.apply_changes(app, changes)
