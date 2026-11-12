"""Put an inserted component's origin where the caller asked.

``IAssemblyDoc::AddComponent4`` and ``AddComponent5`` take the position of
the component's centre, not its origin: a part inserted at (0, 0, 0) landed
offset by minus its bounding-box centre, (0, -6.75, +3.7) mm, and every part
mated to it followed (Cellvis DishRack, 2026-11-12). So ``insert_component``
moves the component afterwards. ``IComponent2.Transform2`` is the component's
placement in the assembly, a ``MathTransform`` whose ``ArrayData`` is 16
doubles: a 3x3 rotation, the translation (metres), a scale and three unused.
It is set to the same rotation with the asked translation, made with
``IMathUtility::CreateTransform``. A fixed component (the first one in an
assembly is fixed) is floated for the move and fixed again, as a script that
moved components on SolidWorks 2026 had to do.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .. import sw_type_info as _sw_type_info
from .com_utils import attempt as _attempt
from .com_utils import double_array as _double_array
from .com_utils import flag as _flag

#: How far (metres) the read-back origin may be from the one asked.
TOLERANCE_M = 1e-7


def translated(data: Sequence[float], origin_m: Sequence[float]) -> list[float]:
    """``ArrayData`` with its translation replaced, rotation and scale kept.

    Raises:
        ValueError: ``data`` isn't the 16 values of a ``MathTransform``.
    """
    values = [float(v) for v in data]
    if len(values) != 16:
        raise ValueError(f"A transform has 16 values, not {len(values)}.")
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


def place_origin(
    adapter: Any,
    model: Any,
    assembly: Any,
    component: Any,
    origin_m: Sequence[float],
) -> dict[str, Any]:
    """Move ``component`` so its origin is at ``origin_m``, keeping its rotation.

    Args:
        adapter: A connected ``PyWin32Adapter``.
        model: The assembly as ``IModelDoc2``.
        assembly: The assembly as ``IAssemblyDoc``.
        component: The inserted ``IComponent2``.
        origin_m: Where its origin goes, in metres.

    Returns:
        dict[str, Any]: ``placed`` (the origin read back is where asked),
        ``origin_mm`` and ``rotation`` as read back, and ``moved`` (it was
        elsewhere). Without a readable transform, ``placed`` is False and
        nothing else is known.
    """
    data = _transform_data(adapter, component)
    if data is None:
        return {"placed": False, "moved": False}
    if _at(data, origin_m):
        return {"placed": True, "moved": False, **describe(data)}
    fixed = bool(_attempt(adapter, lambda: component.IsFixed(), False))
    if fixed:
        _set_fixed(adapter, model, assembly, component, False)
    utility = adapter.swApp.GetMathUtility()
    # Unflagged, late binding reads a method as a property: "Member not found"
    # (live, 2026-11-12; CLAUDE.md "Method flagging via sw_type_info").
    _flag(adapter, utility, "CreateTransform")
    transform = utility.CreateTransform(_double_array(translated(data, origin_m)))
    component.Transform2 = transform
    if fixed:
        _set_fixed(adapter, model, assembly, component, True)
    _attempt(adapter, lambda: model.EditRebuild3())
    after = _transform_data(adapter, component) or data
    return {"placed": _at(after, origin_m), "moved": True, **describe(after)}


def _at(data: Sequence[float], origin_m: Sequence[float]) -> bool:
    return all(
        abs(float(a) - float(b)) <= TOLERANCE_M
        for a, b in zip(data[9:12], origin_m, strict=True)
    )
