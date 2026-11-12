"""STL mesh settings for one export, put back afterwards (``stl_settings``)."""

from __future__ import annotations

import math
import os
from pathlib import Path
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
            ("toggle", stl.STL_ONE_FILE): False,
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

    # The tolerances first: SolidWorks takes custom only once they're written.
    assert [(kind, pref) for kind, pref, _v, _l in changes] == [
        ("double", stl.STL_DEVIATION),
        ("double", stl.STL_ANGLE_TOLERANCE),
        ("integer", stl.STL_QUALITY),
        ("integer", stl.STL_UNITS),
        ("toggle", stl.STL_BINARY),
    ]
    values = [value for _k, _p, value, _l in changes]
    assert values[0] == pytest.approx(1e-5)
    assert values[1] == pytest.approx(math.radians(5))
    assert values[2:] == [3, 0, False]
    assert [label for *_rest, label in changes] == [
        "deviation 0.01 mm",
        "angle 5 deg",
        "resolution custom",
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
        ({"resolution": "custom"}, "Resolution 'custom' needs deviation_mm"),
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

    applied = stl.apply_changes(app, changes)

    assert applied.labels == ["deviation 0.01 mm", "resolution custom", "units mm"]
    assert app.values[("integer", stl.STL_QUALITY)] == 3
    assert app.values[("integer", stl.STL_UNITS)] == 0
    assert stl.restore(app, applied.previous) == []
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


def test_custom_resolution_is_not_checked_and_comes_back_last() -> None:
    """SolidWorks reports custom only while the tolerances are off its presets."""
    app = _App(refuse={stl.STL_QUALITY})
    changes = stl.preference_changes({"angle_deg": 5})

    applied = stl.apply_changes(app, changes)
    app.writes.clear()
    stl.restore(app, applied.previous)

    assert [pref for pref, _value in app.writes] == [
        stl.STL_ANGLE_TOLERANCE,
        stl.STL_QUALITY,
    ]


class _Clamping(_App):
    """SolidWorks keeps the deviation at or above a limit for the part."""

    def _set(self, kind: str, pref: int, value: Any) -> bool:
        if pref == stl.STL_DEVIATION:
            value = max(value, 1.2e-5)
        if pref == stl.STL_ANGLE_TOLERANCE:
            value = max(value, math.radians(5))
        return super()._set(kind, pref, value)


def test_a_tolerance_solidworks_moves_is_reported_as_used() -> None:
    app = _Clamping()
    changes = stl.preference_changes({"deviation_mm": 0.005, "angle_deg": 2})

    applied = stl.apply_changes(app, changes)

    assert applied.labels == [
        "deviation 0.005 mm (SolidWorks used 0.012 mm)",
        "angle 2 deg (SolidWorks used 5 deg)",
        "resolution custom",
    ]
    # Rounding is not a move: 0.005 mm read back as 0.005004 mm.
    assert stl.same_value("double", 5e-6, 5.004e-6)


def test_a_setting_that_cannot_be_put_back_is_counted() -> None:
    app = _App(refuse={stl.STL_UNITS}, broken={stl.STL_QUALITY})
    changes = stl.preference_changes({"resolution": "fine", "units": "m"})

    with pytest.raises(RuntimeError, match="1 setting\\(s\\) could not be put back"):
        stl.apply_changes(app, changes)


@pytest.mark.parametrize(
    ("value", "name"),
    [(0, "mm"), (1, "cm"), (2, "m"), (3, "in"), (4, "ft"), (9, None), (None, None)],
)
def test_the_unit_an_stl_is_written_in(value: Any, name: str | None) -> None:
    assert stl.unit_name(value) == name


def test_the_one_file_option_is_set_for_the_export_and_put_back() -> None:
    app = _App()

    applied = stl.apply_changes(app, [stl.ONE_FILE])

    assert applied.labels == ["all components in one file"]
    assert app.values[("toggle", stl.STL_ONE_FILE)] is True
    assert stl.restore(app, applied.previous) == []
    assert app.values[("toggle", stl.STL_ONE_FILE)] is False


def _touch(path: Path, mtime_ns: int | None = None) -> Path:
    path.write_bytes(b"solid")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def test_files_written_per_component_are_named(tmp_path: Path) -> None:
    target = tmp_path / "rack.stl"
    stale = _touch(tmp_path / "rack - Old-1.STL", 1_000_000_000)
    _touch(tmp_path / "rack.step")
    (tmp_path / "rack - folder.stl").mkdir()
    before = stl.component_files(str(target))
    _touch(tmp_path / "rack - Assembly-1 Part-1.STL", 2_000_000_000)
    _touch(tmp_path / "RACK - Part-2.stl", 2_000_000_000)
    _touch(tmp_path / "racks - Part-3.stl", 2_000_000_000)

    assert before == {str(stale): 1_000_000_000}
    with pytest.raises(RuntimeError) as caught:
        stl.refuse_split_export(str(target), before)

    assert str(caught.value) == (
        f"SolidWorks wrote 2 STL files, one per component, in {tmp_path} "
        "instead of rack.stl: RACK - Part-2.stl, rack - Assembly-1 Part-1.STL. "
        "Its option to save all components in one file did not take; delete "
        "those files, or use them."
    )


def test_a_file_an_earlier_export_left_counts_once_rewritten(tmp_path: Path) -> None:
    target = tmp_path / "rack.stl"
    stale = _touch(tmp_path / "rack - Part-1.stl", 1_000_000_000)
    before = stl.component_files(str(target))

    stl.refuse_split_export(str(target), before)  # nothing new: no error
    _touch(stale, 3_000_000_000)

    with pytest.raises(RuntimeError, match="wrote 1 STL files"):
        stl.refuse_split_export(str(target), before)


def test_a_long_list_of_split_files_is_cut_short(tmp_path: Path) -> None:
    target = tmp_path / "rack.stl"
    for number in range(14):
        _touch(tmp_path / f"rack - Part-{number:02d}.STL")

    with pytest.raises(RuntimeError) as caught:
        stl.refuse_split_export(str(target), {})

    assert "rack - Part-11.STL and 2 more. Its option" in str(caught.value)
