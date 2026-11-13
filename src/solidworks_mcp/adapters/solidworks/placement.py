"""Place a component in its assembly: origin, rotation and fixed state.

``IAssemblyDoc::AddComponent4`` and ``AddComponent5`` take the position of
the component's centre, not its origin: a part inserted at (0, 0, 0) landed
offset by minus its bounding-box centre, (0, -6.75, +3.7) mm, and every part
mated to it followed (Cellvis DishRack, 2026-11-12). So ``insert_component``
moves the component afterwards, and ``set_component_transform`` sets its
origin and rotation (change ``cellvis-assembly-and-print-checks``, D1).

``IComponent2.Transform2`` is the component's placement in the assembly, a
``MathTransform`` whose ``ArrayData`` is 16 doubles: a 3x3 rotation, the
translation (metres), a scale and three unused. A point of the component
goes to ``p . R + t``, so each row of ``R`` is one of the component's axes in
assembly coordinates. The transform is made with
``IMathUtility::CreateTransform`` (flagged first: pitfall #41). A fixed
component (the first one in an assembly is fixed) is floated for the move and
left fixed or floating as asked, as a script that moved components on
SolidWorks 2026 had to do.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .. import sw_type_info as _sw_type_info
from .com_utils import attempt as _attempt
from .com_utils import double_array as _double_array
from .com_utils import flag as _flag

#: How far (metres) the read-back origin may be from the one asked.
TOLERANCE_M = 1e-7

#: How far a read-back rotation entry may be from the one asked.
ROTATION_TOLERANCE = 1e-6

Rows = list[list[float]]


def rotation_rows_from_deg(rx: float, ry: float, rz: float) -> Rows:
    """The rotation rows for turns about the assembly's X, then Y, then Z.

    Each turn follows the right-hand rule. In the ``p . R`` convention the
    rows are the images of the component's X, Y and Z axes: a quarter turn
    about Y sends the X axis to [0, 0, -1].
    """
    rows = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for axis, degrees in enumerate((rx, ry, rz)):
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        # The next two axes in cyclic order: (y, z) about X, (z, x) about Y,
        # (x, y) about Z; u turns toward v.
        u, v = (axis + 1) % 3, (axis + 2) % 3
        turn = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
        turn[u][u], turn[u][v], turn[v][u], turn[v][v] = c, s, -s, c
        rows = [
            [sum(row[k] * turn[k][j] for k in range(3)) for j in range(3)]
            for row in rows
        ]
    return [[round(x, 15) + 0.0 for x in row] for row in rows]


def rotation_problem(rows: Sequence[Sequence[float]]) -> str | None:
    """What is wrong with a rotation given as three rows, or None.

    The rows must be unit length, at right angles and right-handed (a mirror
    is not a placement), within :data:`ROTATION_TOLERANCE`.
    """
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        return "matrix must be three rows of three numbers"
    r = [[float(x) for x in row] for row in rows]
    for i in range(3):
        for j in range(3):
            dot = sum(r[i][k] * r[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > ROTATION_TOLERANCE:
                return (
                    "matrix rows must be unit vectors at right angles (an "
                    "orthonormal rotation)"
                )
    det = (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )
    if det < 0:
        return "matrix is a mirror (determinant -1), not a rotation"
    return None


def transformed(
    data: Sequence[float],
    origin_m: Sequence[float],
    rotation_rows: Sequence[Sequence[float]] | None = None,
) -> list[float]:
    """``ArrayData`` with a new translation, and rotation when given; scale kept.

    Raises:
        ValueError: ``data`` isn't the 16 values of a ``MathTransform``.
    """
    values = [float(v) for v in data]
    if len(values) != 16:
        raise ValueError(f"A transform has 16 values, not {len(values)}.")
    if rotation_rows is not None:
        values[0:9] = [float(x) for row in rotation_rows for x in row]
    values[9:12] = [float(c) for c in origin_m]
    return values


def describe(data: Sequence[float]) -> dict[str, Any]:
    """A transform's origin in mm and its rotation rows, rounded."""
    values = [float(v) for v in data]
    return {
        "origin_mm": [round(v * 1000.0, 6) + 0.0 for v in values[9:12]],
        "rotation": [
            [round(v, 9) + 0.0 for v in values[row : row + 3]] for row in (0, 3, 6)
        ],
    }


def _transform_data(adapter: Any, component: Any) -> list[float] | None:
    transform = _attempt(adapter, lambda: component.Transform2)
    data = _attempt(adapter, lambda: transform.ArrayData) if transform else None
    if not isinstance(data, (list, tuple)) or len(data) != 16:
        return None
    return [float(v) for v in data]


def _is_fixed(adapter: Any, component: Any) -> bool:
    return bool(_attempt(adapter, lambda: component.IsFixed(), False))


def _set_fixed(
    adapter: Any, model: Any, assembly: Any, component: Any, fix: bool
) -> None:
    """Select ``component`` alone and fix or float it."""
    _attempt(adapter, lambda: model.ClearSelection2(True))
    selection = _attempt(
        adapter,
        lambda: _sw_type_info.flagged(
            model.SelectionManager, "ISelectionMgr"
        ).CreateSelectData(),
    )
    if _attempt(adapter, lambda: component.Select4(False, selection, False), False):
        _attempt(adapter, assembly.FixComponent if fix else assembly.UnfixComponent)
    _attempt(adapter, lambda: model.ClearSelection2(True))


def place(
    adapter: Any,
    model: Any,
    assembly: Any,
    component: Any,
    origin_m: Sequence[float],
    rotation_rows: Sequence[Sequence[float]] | None = None,
    fixed: bool | None = None,
) -> dict[str, Any]:
    """Put ``component``'s origin at ``origin_m`` and its axes along the rows.

    Args:
        adapter: A connected ``PyWin32Adapter``.
        model: The assembly as ``IModelDoc2``.
        assembly: The assembly as ``IAssemblyDoc``.
        component: The ``IComponent2``.
        origin_m: Where its origin goes, in metres.
        rotation_rows: Its axes in assembly coordinates; None keeps them.
        fixed: Fix (True) or float (False) it afterwards; None keeps the
            state it had.

    Returns:
        dict[str, Any]: ``placed`` (the transform read back is the one
        asked), ``moved`` (it had to move), ``fixed`` as read back, and
        ``origin_mm`` and ``rotation`` as read back. Without a readable
        transform, ``placed`` and ``moved`` are False and nothing else is
        known.
    """
    data = _transform_data(adapter, component)
    if data is None:
        return {"placed": False, "moved": False}
    was_fixed = _is_fixed(adapter, component)
    wanted_fixed = was_fixed if fixed is None else bool(fixed)
    moved = not _matches(data, origin_m, rotation_rows)
    if moved:
        if was_fixed:
            _set_fixed(adapter, model, assembly, component, False)
        utility = adapter.swApp.GetMathUtility()
        # Unflagged, late binding reads a method as a property: "Member not
        # found" (live, 2026-11-12; CLAUDE.md "Method flagging via sw_type_info").
        _flag(adapter, utility, "CreateTransform")
        values = transformed(data, origin_m, rotation_rows)
        component.Transform2 = utility.CreateTransform(_double_array(values))
        if wanted_fixed:
            _set_fixed(adapter, model, assembly, component, True)
    elif wanted_fixed != was_fixed:
        _set_fixed(adapter, model, assembly, component, wanted_fixed)
    _attempt(adapter, lambda: model.EditRebuild3())
    after = _transform_data(adapter, component) or data
    return {
        "placed": _matches(after, origin_m, rotation_rows),
        "moved": moved,
        "fixed": _is_fixed(adapter, component),
        **describe(after),
    }


def place_origin(
    adapter: Any,
    model: Any,
    assembly: Any,
    component: Any,
    origin_m: Sequence[float],
    fixed: bool | None = None,
) -> dict[str, Any]:
    """:func:`place` with the rotation kept (``insert_component``)."""
    return place(adapter, model, assembly, component, origin_m, None, fixed)


def _matches(
    data: Sequence[float],
    origin_m: Sequence[float],
    rotation_rows: Sequence[Sequence[float]] | None,
) -> bool:
    at = all(
        abs(float(a) - float(b)) <= TOLERANCE_M
        for a, b in zip(data[9:12], origin_m, strict=True)
    )
    if not at or rotation_rows is None:
        return at
    wanted = [float(x) for row in rotation_rows for x in row]
    return all(
        abs(float(a) - b) <= ROTATION_TOLERANCE
        for a, b in zip(data[0:9], wanted, strict=True)
    )
