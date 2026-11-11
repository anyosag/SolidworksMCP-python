"""STL export settings for one export, put back afterwards.

SolidWorks keeps the STL options (Tools > Options > Export > STL) as the
user's application preferences, so an export that needs a finer mesh or other
units changes them, exports, and restores what the user had. Values are from
the SolidWorks 2026 ``swconst`` help ("System Options > Export > STL"):

* resolution: ``swSTLQuality`` (integer 78), ``swSTLQuality_e`` coarse 1,
  fine 2, custom 3;
* deviation and angle tolerance: ``swSTLDeviation`` and
  ``swSTLAngleTolerance`` (doubles 2 and 3), used with custom resolution.
  The help gives no unit; they are written in SolidWorks' system units,
  metres and radians, like the rest of the API;
* units: ``swExportStlUnits`` (integer 211), ``swLengthUnit_e`` mm 0, cm 1,
  m 2, in 3, ft 4;
* binary or ASCII: ``swSTLBinaryFormat`` (toggle 69).
"""

from __future__ import annotations

import math
from typing import Any

#: The kinds of preference, and the ISldWorks get/set methods for each.
PREFERENCE_METHODS: dict[str, tuple[str, str]] = {
    "integer": ("GetUserPreferenceIntegerValue", "SetUserPreferenceIntegerValue"),
    "double": ("GetUserPreferenceDoubleValue", "SetUserPreferenceDoubleValue"),
    "toggle": ("GetUserPreferenceToggle", "SetUserPreferenceToggle"),
}

STL_QUALITY = 78
STL_DEVIATION = 2
STL_ANGLE_TOLERANCE = 3
STL_UNITS = 211
STL_BINARY = 69

RESOLUTIONS = {"coarse": 1, "fine": 2, "custom": 3}
UNITS = {"mm": 0, "cm": 1, "m": 2, "in": 3, "ft": 4}

#: One preference to change: (kind, swUserPreference id, value, label).
Change = tuple[str, int, Any, str]


def preference_changes(settings: dict[str, Any]) -> list[Change]:
    """The preferences to set for ``settings`` (keys left out keep the user's).

    Args:
        settings: Any of ``resolution``, ``deviation_mm``, ``angle_deg``,
            ``units`` and ``binary``. A deviation or angle implies custom
            resolution.

    Returns:
        list[Change]: In the order to set them.

    Raises:
        ValueError: For a coarse or fine resolution with a deviation or angle,
            or an unknown resolution or unit.
    """
    changes: list[Change] = []
    resolution = settings.get("resolution")
    tolerances = [
        key for key in ("deviation_mm", "angle_deg") if settings.get(key) is not None
    ]
    if tolerances and resolution not in (None, "custom"):
        raise ValueError(
            f"{' and '.join(tolerances)} need resolution 'custom', not {resolution!r}."
        )
    if tolerances:
        resolution = "custom"
    if resolution is not None:
        if resolution not in RESOLUTIONS:
            raise ValueError(f"Unknown STL resolution {resolution!r}.")
        changes.append(
            (
                "integer",
                STL_QUALITY,
                RESOLUTIONS[resolution],
                f"resolution {resolution}",
            )
        )
    if settings.get("deviation_mm") is not None:
        mm = float(settings["deviation_mm"])
        changes.append(("double", STL_DEVIATION, mm / 1000.0, f"deviation {mm:g} mm"))
    if settings.get("angle_deg") is not None:
        deg = float(settings["angle_deg"])
        changes.append(
            ("double", STL_ANGLE_TOLERANCE, math.radians(deg), f"angle {deg:g} deg")
        )
    if settings.get("units") is not None:
        units = str(settings["units"])
        if units not in UNITS:
            raise ValueError(f"Unknown STL units {units!r}.")
        changes.append(("integer", STL_UNITS, UNITS[units], f"units {units}"))
    if settings.get("binary") is not None:
        binary = bool(settings["binary"])
        changes.append(("toggle", STL_BINARY, binary, "binary" if binary else "ASCII"))
    return changes


def same_value(kind: str, wanted: Any, read: Any) -> bool:
    """Whether a preference read back holds the value written."""
    if read is None:
        return False
    if kind == "double":
        return math.isclose(float(read), float(wanted), rel_tol=1e-6, abs_tol=1e-12)
    if kind == "toggle":
        return bool(read) is bool(wanted)
    return int(read) == int(wanted)


def apply_changes(app: Any, changes: list[Change]) -> list[tuple[str, int, Any]]:
    """Set each preference, reading the user's value first and checking each.

    Args:
        app: ``ISldWorks`` (its get/set methods flagged).
        changes: From :func:`preference_changes`.

    Returns:
        list[tuple[str, int, Any]]: ``(kind, id, previous)`` for every
        preference set, for :func:`restore`.

    Raises:
        RuntimeError: When SolidWorks doesn't take a value; the ones set
            before it are put back first.
    """
    previous: list[tuple[str, int, Any]] = []
    for kind, pref, value, label in changes:
        getter, setter = PREFERENCE_METHODS[kind]
        old = getattr(app, getter)(pref)
        getattr(app, setter)(pref, value)
        previous.append((kind, pref, old))
        if not same_value(kind, value, getattr(app, getter)(pref)):
            failed = restore(app, previous)
            raise RuntimeError(
                f"SolidWorks did not take the STL setting {label}, so nothing "
                "was exported"
                + (
                    f"; {len(failed)} setting(s) could not be put back"
                    if failed
                    else "; your STL options are as they were"
                )
                + "."
            )
    return previous


def restore(app: Any, previous: list[tuple[str, int, Any]]) -> list[int]:
    """Put back the user's values, last set first.

    Returns:
        list[int]: The preference ids that could not be put back.
    """
    failed = []
    for kind, pref, old in reversed(previous):
        _getter, setter = PREFERENCE_METHODS[kind]
        try:
            getattr(app, setter)(pref, old)
        except Exception:
            failed.append(pref)
    return failed
