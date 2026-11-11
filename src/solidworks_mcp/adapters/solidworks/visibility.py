"""Show and hide reference geometry and sketches in the active document.

Two ways, as in SolidWorks' own UI:

* **By type** (View > Hide/Show): every plane, axis, sketch... of the
  document at once, through the document's display toggles
  (``IModelDocExtension.SetUserPreferenceToggle``). The previous values are
  returned, so a caller can put them back; ``export_image`` uses this to
  take a picture without planes and sketches, then restores them.
* **By name**: one feature, selected then hidden with ``BlankRefGeom`` /
  ``BlankSketch`` (shown again with ``UnBlankRefGeom`` / ``UnblankSketch``),
  the API calls behind the tree's Hide and Show.

The toggle values are ``swUserPreferenceToggle_e`` members, read from
SolidWorks 2026's ``swconst.tlb``.
"""

from __future__ import annotations

from typing import Any

from .com_utils import attempt as _attempt
from .com_utils import flag as _flag

#: Display types by the name the tool takes -> ``swUserPreferenceToggle_e``.
DISPLAY_TOGGLES: dict[str, int] = {
    "planes": 5,  # swDisplayPlanes
    "axes": 4,  # swDisplayAxes
    "temporary_axes": 7,  # swDisplayTemporaryAxes
    "origins": 6,  # swDisplayOrigins
    "coordinate_systems": 13,  # swDisplayCoordSystems
    "points": 19,  # swDisplayReferencePoints
    "sketches": 196,  # swDisplaySketches
}

#: ``swUserPreferenceOption_e.swDetailingNoOptionSpecified``: the toggle is
#: the document's, not a detailing option's.
_NO_OPTION = 0

#: ``IFeature.GetTypeName2`` of the features hidden with ``BlankSketch``.
SKETCH_TYPES = frozenset({"ProfileFeature", "3DProfileFeature"})
#: ... and of those hidden with ``BlankRefGeom``.
REFERENCE_TYPES = frozenset({"RefPlane", "RefAxis", "RefPoint", "CoordSys"})


def unknown_types(types: list[str]) -> list[str]:
    """The names in ``types`` that aren't display types."""
    return [t for t in types if t not in DISPLAY_TOGGLES]


def set_display_types(
    adapter: Any, types: list[str], visible: bool, model: Any = None
) -> dict[str, Any]:
    """Show or hide every entity of each type in a document.

    Args:
        adapter: A connected adapter with a ``currentModel``.
        types: Keys of :data:`DISPLAY_TOGGLES`.
        visible: Show (True) or hide (False).
        model: The document (default: the adapter's ``currentModel``).

    Returns:
        dict[str, Any]: Per type, ``{"before": bool | None, "after": bool |
        None}`` as SolidWorks reports the toggle (None when it can't be read).

    Raises:
        RuntimeError: SolidWorks kept a toggle at the old value.
    """
    model = model if model is not None else adapter.currentModel
    extension = model.Extension
    _flag(adapter, extension, "GetUserPreferenceToggle", "SetUserPreferenceToggle")
    changed: dict[str, Any] = {}
    for name in types:
        toggle = DISPLAY_TOGGLES[name]
        before = _attempt(
            adapter, lambda t=toggle: extension.GetUserPreferenceToggle(t, _NO_OPTION)
        )
        _attempt(
            adapter,
            lambda t=toggle: extension.SetUserPreferenceToggle(
                t, _NO_OPTION, bool(visible)
            ),
        )
        after = _attempt(
            adapter, lambda t=toggle: extension.GetUserPreferenceToggle(t, _NO_OPTION)
        )
        if after is not None and bool(after) != bool(visible):
            raise RuntimeError(
                f"SolidWorks kept {name} {'hidden' if visible else 'shown'}"
            )
        changed[name] = {
            "before": None if before is None else bool(before),
            "after": None if after is None else bool(after),
        }
    _attempt(adapter, lambda: model.GraphicsRedraw2())
    return changed


def restore_display_types(
    adapter: Any, changed: dict[str, Any], model: Any = None
) -> None:
    """Put back toggles ``set_display_types`` changed, from their ``before``."""
    model = model if model is not None else adapter.currentModel
    extension = model.Extension
    _flag(adapter, extension, "SetUserPreferenceToggle")
    for name, state in changed.items():
        if state.get("before") is None:
            continue
        _attempt(
            adapter,
            lambda n=name, s=state: extension.SetUserPreferenceToggle(
                DISPLAY_TOGGLES[n], _NO_OPTION, bool(s["before"])
            ),
        )
    _attempt(adapter, lambda: model.GraphicsRedraw2())


def set_feature_visibility(
    adapter: Any, names: list[str], visible: bool
) -> list[dict[str, Any]]:
    """Show or hide named planes, axes, points, coordinate systems and sketches.

    Args:
        adapter: A connected adapter with a ``currentModel``.
        names: Feature names as the tree shows them.
        visible: Show (True) or hide (False).

    Returns:
        list[dict[str, Any]]: ``{"name", "type", "visible"}`` per name.

    Raises:
        LookupError: A name isn't in the tree.
        ValueError: A feature isn't something that can be hidden this way
            (a boss, a cut: suppress it instead).
        RuntimeError: SolidWorks couldn't select it.
    """
    model = adapter.currentModel
    _flag(
        adapter,
        model,
        "BlankRefGeom",
        "UnBlankRefGeom",
        "BlankSketch",
        "UnblankSketch",
        "ClearSelection2",
    )
    done = []
    for name in names:
        feature = _attempt(adapter, lambda n=name: model.FeatureByName(n))
        if feature is None:
            raise LookupError(f"Feature {name!r} not found; list_features names them.")
        _flag(adapter, feature, "GetTypeName2", "Select2")
        kind = str(_attempt(adapter, lambda f=feature: f.GetTypeName2()) or "")
        if kind in SKETCH_TYPES:
            method = "UnblankSketch" if visible else "BlankSketch"
        elif kind in REFERENCE_TYPES:
            method = "UnBlankRefGeom" if visible else "BlankRefGeom"
        else:
            raise ValueError(
                f"{name!r} is a {kind or 'feature'}, not a plane, axis, point, "
                "coordinate system or sketch; use suppress_feature to turn a "
                "feature off"
            )
        _attempt(adapter, lambda: model.ClearSelection2(True))
        if not _attempt(adapter, lambda f=feature: f.Select2(False, 0), False):
            raise RuntimeError(
                f"SolidWorks could not select {name!r} to hide or show it"
            )
        # Zero-argument methods: flagged they are callable, unflagged the
        # attribute read runs them; _get_attr_or_call runs them once either way.
        adapter._get_attr_or_call(model, method)
        _attempt(adapter, lambda: model.ClearSelection2(True))
        done.append({"name": name, "type": kind, "visible": bool(visible)})
    return done
