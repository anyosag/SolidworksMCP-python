"""A section view for one picture (``section_view``), on fake COM objects."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import section_view


class _Adapter:
    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001 - mirror the real adapter
            return default


class _Feature:
    def __init__(self, kind: str = "RefPlane", plane: Any = "front-ref-plane") -> None:
        self._kind, self._plane = kind, plane

    def GetTypeName2(self) -> str:  # noqa: N802
        return self._kind

    def GetSpecificFeature2(self) -> Any:  # noqa: N802
        return self._plane


class _Manager:
    def __init__(self, creates: bool = True, removes: Any = True) -> None:
        self.data = SimpleNamespace()
        self.creates, self.removes = creates, removes
        self.created: list[Any] = []
        self.removed = 0

    def CreateSectionViewData(self) -> Any:  # noqa: N802
        return self.data

    def CreateSectionView(self, data: Any) -> bool:  # noqa: N802
        self.created.append(data)
        return self.creates

    def RemoveSectionView(self) -> bool:  # noqa: N802
        self.removed += 1
        if isinstance(self.removes, Exception):
            raise self.removes
        return self.removes


class _Model:
    def __init__(self, features: dict[str, Any], manager: Any = None) -> None:
        self._features = features
        self.ModelViewManager = _Manager() if manager is None else manager

    def FeatureByName(self, name: str) -> Any:  # noqa: N802
        return self._features.get(name)


def test_a_plane_is_found_by_name() -> None:
    model = _Model({"Front Plane": _Feature()})

    assert (
        section_view.find_plane(_Adapter(), model, "Front Plane") == "front-ref-plane"
    )


@pytest.mark.parametrize(
    ("features", "fragment"),
    [
        ({}, "the model has no plane named 'Plane9'"),
        ({"Plane9": _Feature("Extrusion")}, "'Plane9' is a Extrusion, not a plane"),
        ({"Plane9": _Feature(None)}, "'Plane9' is a feature, not a plane"),  # type: ignore[arg-type]
        ({"Plane9": _Feature(plane=None)}, "could not be read"),
    ],
)
def test_no_plane_of_that_name_is_not_found(
    features: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(LookupError) as caught:
        section_view.find_plane(_Adapter(), _Model(features), "Plane9")

    assert str(caught.value).startswith("Section plane not found: ")
    assert fragment in str(caught.value)
    assert "no picture was taken" in str(caught.value)


def test_the_section_is_set_in_metres_with_a_cap() -> None:
    model = _Model({})

    applied = section_view.apply(
        _Adapter(),
        model,
        "front-ref-plane",
        {"plane": "Front Plane", "offset_mm": 2.5, "reverse": True},
    )

    data = model.ModelViewManager.data
    assert model.ModelViewManager.created == [data]
    assert data.FirstPlane == "front-ref-plane"
    assert data.FirstOffset == pytest.approx(0.0025)
    assert data.FirstReverseDirection is True
    assert data.ShowSectionCap is True
    assert applied == {
        "plane": "Front Plane",
        "offset_mm": 2.5,
        "reverse": True,
        "removed": False,
    }


def test_offset_and_reverse_default_to_zero_and_false() -> None:
    model = _Model({})

    applied = section_view.apply(_Adapter(), model, "p", {"plane": "Top Plane"})

    assert (applied["offset_mm"], applied["reverse"]) == (0.0, False)
    assert model.ModelViewManager.data.FirstOffset == 0.0


def test_a_refused_section_says_so() -> None:
    model = _Model({}, _Manager(creates=False))

    with pytest.raises(RuntimeError, match="refused the section on Front Plane"):
        section_view.apply(_Adapter(), model, "p", {"plane": "Front Plane"})


@pytest.mark.parametrize(
    "manager",
    [None, SimpleNamespace(CreateSectionViewData=lambda: None)],
)
def test_no_section_data_says_so(manager: Any) -> None:
    model = _Model({})
    model.ModelViewManager = manager

    with pytest.raises(RuntimeError, match="no section view data"):
        section_view.apply(_Adapter(), model, "p", {"plane": "Front Plane"})


@pytest.mark.parametrize(
    ("removes", "expected"),
    [(True, True), (False, False), (RuntimeError("COM"), False)],
)
def test_removing_reports_whether_it_went(removes: Any, expected: bool) -> None:
    model = _Model({}, _Manager(removes=removes))

    assert section_view.remove(_Adapter(), model) is expected
    assert model.ModelViewManager.removed == 1


def test_removing_without_a_view_manager_is_not_removed() -> None:
    model = _Model({})
    model.ModelViewManager = None

    assert section_view.remove(_Adapter(), model) is False
