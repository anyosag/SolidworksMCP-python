"""A section view for one picture: ``export_image``'s ``section``.

A snap inside its socket can't be seen from outside (Cellvis dish rack,
2026-11-12), so ``export_image`` can cut the model on a plane for one
picture and take the cut off again (change
``cellvis-assembly-and-print-checks``, D3).

The COM calls, as probe 2 ran them on SOLIDWORKS 2026 SP4.1
(``tests/scripts/probe_section_fillet.py``):

* the plane: ``IModelDoc2.FeatureByName(name)``, then
  ``IFeature.GetSpecificFeature2()`` (the ``IRefPlane``);
* ``IModelViewManager.CreateSectionViewData()`` (flagged: it takes no
  arguments), with ``FirstPlane``, ``FirstOffset`` (metres),
  ``FirstReverseDirection`` and ``ShowSectionCap`` put on the
  ``ISectionViewData``;
* ``IModelViewManager.CreateSectionView(data)``: True, and 22.5% of the
  picture's pixels changed;
* ``IModelViewManager.RemoveSectionView()`` (flagged): True, and the next
  picture was identical to the one before the section.
"""

from __future__ import annotations

from typing import Any

from .com_utils import attempt as _attempt
from .com_utils import flag as _flag

#: ``IFeature.GetTypeName2`` of a reference plane, standard planes included.
PLANE_TYPE = "RefPlane"


def find_plane(adapter: Any, model: Any, name: str) -> Any:
    """The plane named ``name`` in ``model``, as ``IRefPlane``.

    Args:
        adapter: A connected adapter.
        model: The document to cut, as ``IModelDoc2``.
        name: The plane's tree name, e.g. ``Front Plane`` or ``Plane1``.

    Returns:
        Any: The ``IRefPlane`` to put on ``ISectionViewData.FirstPlane``.

    Raises:
        LookupError: No feature has that name, it isn't a plane, or its plane
            can't be read. Nothing has been changed.
    """
    _flag(adapter, model, "FeatureByName")
    feature = _attempt(adapter, lambda: model.FeatureByName(name))
    if feature is None:
        raise LookupError(
            f"Section plane not found: the model has no plane named {name!r}, "
            "so no picture was taken. Use a plane's name from list_features, "
            "such as Front Plane."
        )
    _flag(adapter, feature, "GetTypeName2", "GetSpecificFeature2")
    kind = _attempt(adapter, lambda: feature.GetTypeName2())
    if kind != PLANE_TYPE:
        raise LookupError(
            f"Section plane not found: {name!r} is a {kind or 'feature'}, not a "
            "plane, so no picture was taken."
        )
    plane = _attempt(adapter, lambda: feature.GetSpecificFeature2())
    if plane is None:
        raise LookupError(
            f"Section plane not found: the plane {name!r} could not be read "
            "(GetSpecificFeature2), so no picture was taken."
        )
    return plane


def _manager(adapter: Any, model: Any) -> Any:
    """The document's ``IModelViewManager``, its methods flagged."""
    manager = _attempt(adapter, lambda: model.ModelViewManager)
    _flag(
        adapter,
        manager,
        "CreateSectionViewData",
        "CreateSectionView",
        "RemoveSectionView",
    )
    return manager


def apply(adapter: Any, model: Any, plane: Any, section: dict[str, Any]) -> dict:
    """Cut the model's view on ``plane``, with the cut faces capped.

    Args:
        adapter: A connected adapter.
        model: The document to cut.
        plane: :func:`find_plane`'s ``IRefPlane``.
        section: ``plane`` (its name), ``offset_mm`` (0) and ``reverse``
            (False: which side is kept).

    Returns:
        dict: The section as applied, for the reply: ``plane``,
        ``offset_mm``, ``reverse`` and ``removed`` (False until
        :func:`remove` takes it off).

    Raises:
        RuntimeError: SolidWorks gave no section data, or refused the section.
    """
    name = str(section.get("plane") or "")
    offset_mm = float(section.get("offset_mm") or 0.0)
    reverse = bool(section.get("reverse", False))
    manager = _manager(adapter, model)
    data = (
        _attempt(adapter, lambda: manager.CreateSectionViewData())
        if manager is not None
        else None
    )
    if data is None:
        raise RuntimeError(
            "SolidWorks gave no section view data (CreateSectionViewData), so no "
            "picture was taken."
        )
    data.FirstPlane = plane
    data.FirstOffset = offset_mm / 1000.0
    data.FirstReverseDirection = reverse
    data.ShowSectionCap = True
    if not manager.CreateSectionView(data):
        raise RuntimeError(
            f"SolidWorks refused the section on {name} (CreateSectionView "
            "returned False), so no picture was taken."
        )
    return {"plane": name, "offset_mm": offset_mm, "reverse": reverse, "removed": False}


def remove(adapter: Any, model: Any) -> bool:
    """Take the section view off the model.

    Returns:
        bool: Whether SolidWorks took it off.
    """
    manager = _manager(adapter, model)
    if manager is None:
        return False
    return bool(_attempt(adapter, lambda: manager.RemoveSectionView(), False))
