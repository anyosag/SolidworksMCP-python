"""STL export settings for one export, put back afterwards.

SolidWorks keeps the STL options (Tools > Options > Export > STL) as the
user's application preferences, so an export that needs a finer mesh or other
units changes them, exports, and restores what the user had. Values are from
the SolidWorks 2026 ``swconst`` help ("System Options > Export > STL"):

* resolution: ``swSTLQuality`` (integer 78), ``swSTLQuality_e`` coarse 1,
  fine 2, custom 3;
* deviation and angle tolerance: ``swSTLDeviation`` and
  ``swSTLAngleTolerance`` (doubles 2 and 3), used with custom resolution.
  The help gives no unit; SolidWorks 2026 stores metres and radians (a
  user's 30 degrees read back as 0.5236);
* units: ``swExportStlUnits`` (integer 211), ``swLengthUnit_e`` mm 0, cm 1,
  m 2, in 3, ft 4;
* binary or ASCII: ``swSTLBinaryFormat`` (toggle 69).

Measured on SolidWorks 2026 (2026-11-11, COM pitfall #40): SolidWorks derives
the resolution from the tolerances. ``swSTLQuality`` = custom is ignored (it
reads back as before) until a tolerance has been written with a value off the
coarse and fine presets, and then it sticks. So tolerances are written first,
custom resolution needs one of them, its read-back is not checked, and on
restore the tolerances go back before the resolution. SolidWorks also keeps
the deviation within limits that depend on the part, so a tolerance it moves
is reported as used, not refused.

An assembly goes into one file only while ``swSTLComponentsIntoOneFile``
(toggle 72) is on. With it off, SolidWorks writes one file per component next
to the one asked for (``X - Assembly-1 Part-1.STL``) and no ``X.stl``, so an
assembly export turns it on for the export (:data:`ONE_FILE`) and
:func:`refuse_split_export` names the files written when that didn't help.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
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
STL_ONE_FILE = 72

RESOLUTIONS = {"coarse": 1, "fine": 2, "custom": 3}
UNITS = {"mm": 0, "cm": 1, "m": 2, "in": 3, "ft": 4}

#: One preference to change: (kind, swUserPreference id, value, label).
Change = tuple[str, int, Any, str]

#: Every component of an assembly in the one file asked for.
ONE_FILE: Change = ("toggle", STL_ONE_FILE, True, "all components in one file")

#: How many split files an error names before "and N more".
_NAMED_FILES = 12


def unit_name(value: Any) -> str | None:
    """The unit name (``mm``, ...) for an ``swExportStlUnits`` value, or ``None``."""
    names = {number: name for name, number in UNITS.items()}
    return names.get(value) if isinstance(value, int) else None


def component_files(path: str) -> dict[str, int]:
    """The per-component files SolidWorks writes for ``path``, with mtimes.

    For ``X.stl`` those are ``X - <component>.stl`` next to it, any case.

    Args:
        path: The ``.stl`` file asked for; its folder must exist.

    Returns:
        dict[str, int]: Each such file's path and ``st_mtime_ns``.
    """
    folder, name = os.path.split(os.path.abspath(path))
    prefix = os.path.splitext(name)[0].lower() + " - "
    found: dict[str, int] = {}
    with os.scandir(folder) as entries:
        for entry in entries:
            lowered = entry.name.lower()
            split = lowered.startswith(prefix) and lowered.endswith(".stl")
            if split and entry.is_file():
                found[entry.path] = entry.stat().st_mtime_ns
    return found


def refuse_split_export(path: str, before: dict[str, int]) -> None:
    """Raise when the export wrote per-component files instead of ``path``.

    Args:
        path: The ``.stl`` file asked for.
        before: :func:`component_files` from before the export, so files an
            earlier export left are not counted.

    Raises:
        RuntimeError: Naming the files written, so they can be deleted or
            used; nothing when there are none.
    """
    written = sorted(
        file
        for file, mtime in component_files(path).items()
        if before.get(file) != mtime
    )
    if not written:
        return
    names = [os.path.basename(file) for file in written]
    shown = ", ".join(names[:_NAMED_FILES])
    if len(names) > _NAMED_FILES:
        shown += f" and {len(names) - _NAMED_FILES} more"
    raise RuntimeError(
        f"SolidWorks wrote {len(names)} STL files, one per component, in "
        f"{os.path.dirname(written[0])} instead of {os.path.basename(path)}: "
        f"{shown}. Its option to save all components in one file did not "
        "take; delete those files, or use them."
    )


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
    if resolution == "custom" and not tolerances:
        raise ValueError(
            "Resolution 'custom' needs deviation_mm or angle_deg: SolidWorks "
            "takes custom only with its own tolerances."
        )
    if tolerances:
        resolution = "custom"
    if resolution is not None and resolution not in RESOLUTIONS:
        raise ValueError(f"Unknown STL resolution {resolution!r}.")
    if settings.get("deviation_mm") is not None:
        mm = float(settings["deviation_mm"])
        changes.append(("double", STL_DEVIATION, mm / 1000.0, f"deviation {mm:g} mm"))
    if settings.get("angle_deg") is not None:
        deg = float(settings["angle_deg"])
        changes.append(
            ("double", STL_ANGLE_TOLERANCE, math.radians(deg), f"angle {deg:g} deg")
        )
    if resolution is not None:
        # After the tolerances: custom only sticks once they are written.
        quality = RESOLUTIONS[resolution]
        changes.append(("integer", STL_QUALITY, quality, f"resolution {resolution}"))
    if settings.get("units") is not None:
        units = str(settings["units"])
        if units not in UNITS:
            raise ValueError(f"Unknown STL units {units!r}.")
        changes.append(("integer", STL_UNITS, UNITS[units], f"units {units}"))
    if settings.get("binary") is not None:
        binary = bool(settings["binary"])
        changes.append(("toggle", STL_BINARY, binary, "binary" if binary else "ASCII"))
    return changes


def same_value(kind: str, wanted: Any, read: Any, pref: int = 0) -> bool:
    """Whether a preference read back holds the value written.

    Custom resolution is not checked: SolidWorks reports custom only while
    the tolerances are off its presets, and uses the tolerances written
    either way.
    """
    if pref == STL_QUALITY and wanted == RESOLUTIONS["custom"]:
        return True
    if read is None:
        return False
    if kind == "double":
        # SolidWorks rounds tolerances (0.005 mm reads back 0.005004 mm).
        return math.isclose(float(read), float(wanted), rel_tol=1e-2, abs_tol=1e-12)
    if kind == "toggle":
        return bool(read) is bool(wanted)
    return int(read) == int(wanted)


@dataclass
class Applied:
    """What :func:`apply_changes` set.

    Attributes:
        previous: ``(kind, id, previous)`` for every preference set, for
            :func:`restore`.
        labels: One line per setting, as SolidWorks took it.
    """

    previous: list[tuple[str, int, Any]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


def _shown(pref: int, raw: Any) -> str:
    """A tolerance in the tools' units: mm for the deviation, else degrees."""
    if pref == STL_DEVIATION:
        return f"{float(raw) * 1000.0:.4g} mm"
    return f"{math.degrees(float(raw)):.4g} deg"


def apply_changes(app: Any, changes: list[Change]) -> Applied:
    """Set each preference, reading the user's value first and checking each.

    A tolerance SolidWorks moves (it keeps the deviation within limits that
    depend on the part: 0.005 mm was refused on a 40 mm disc) is not an
    error: the export uses what SolidWorks holds, and the label says what
    that was.

    Args:
        app: ``ISldWorks`` (its get/set methods flagged).
        changes: From :func:`preference_changes`.

    Returns:
        Applied: The user's values, and a label per setting.

    Raises:
        RuntimeError: When SolidWorks doesn't take a resolution, units or
            format; the ones set before it are put back first.
    """
    applied = Applied()
    previous = applied.previous
    given = {pref for _kind, pref, _value, _label in changes}
    if STL_QUALITY in given:
        # Coarse or fine moves the tolerances to their presets, and a custom
        # resolution comes back only with its tolerances off them: keep the
        # user's tolerances to put back even when this export doesn't set
        # them (live, 2026-11-12: a user's custom 0.033 mm / 10 deg came back
        # as coarse 0.068 mm / 30 deg).
        for pref in (STL_DEVIATION, STL_ANGLE_TOLERANCE):
            if pref not in given:
                getter = PREFERENCE_METHODS["double"][0]
                previous.append(("double", pref, getattr(app, getter)(pref)))
    for kind, pref, value, label in changes:
        getter, setter = PREFERENCE_METHODS[kind]
        old = getattr(app, getter)(pref)
        getattr(app, setter)(pref, value)
        previous.append((kind, pref, old))
        read = getattr(app, getter)(pref)
        if same_value(kind, value, read, pref):
            applied.labels.append(label)
            continue
        if kind == "double" and read is not None:
            applied.labels.append(f"{label} (SolidWorks used {_shown(pref, read)})")
            continue
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
    return applied


def restore(app: Any, previous: list[tuple[str, int, Any]]) -> list[int]:
    """Put back the user's values: the resolution after the tolerances.

    SolidWorks derives the resolution from the tolerances, so the user's
    tolerances go back first and their resolution last.

    Returns:
        list[int]: The preference ids that could not be put back.
    """
    failed = []
    order = [p for p in reversed(previous) if p[1] != STL_QUALITY] + [
        p for p in previous if p[1] == STL_QUALITY
    ]
    for kind, pref, old in order:
        _getter, setter = PREFERENCE_METHODS[kind]
        try:
            getattr(app, setter)(pref, old)
        except Exception:
            failed.append(pref)
    return failed
