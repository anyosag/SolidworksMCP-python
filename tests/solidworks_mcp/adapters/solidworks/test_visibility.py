"""Showing and hiding reference geometry and sketches (``visibility``)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import visibility as vis
from solidworks_mcp.adapters.solidworks.selection import SolidWorksSelectionMixin


class _Extension:
    """Document display toggles, all shown, that can refuse one."""

    def __init__(self, stuck: int | None = None) -> None:
        self.toggles = dict.fromkeys(vis.DISPLAY_TOGGLES.values(), True)
        self.stuck = stuck

    def GetUserPreferenceToggle(self, toggle: int, option: int) -> bool:  # noqa: N802
        assert option == 0
        return self.toggles[toggle]

    def SetUserPreferenceToggle(self, toggle: int, option: int, value: bool) -> None:  # noqa: N802
        assert option == 0
        if toggle != self.stuck:
            self.toggles[toggle] = value


class _Model:
    def __init__(
        self, extension: _Extension | None = None, select_ok: bool = True
    ) -> None:
        self.Extension = extension or _Extension()
        self.calls: list[str] = []
        self.redraws = 0
        kinds = {
            "Plane1": "RefPlane",
            "Axis1": "RefAxis",
            "Sketch2": "ProfileFeature",
            "Boss-Extrude1": "Extrusion",
        }
        self._features = {
            name: SimpleNamespace(
                GetTypeName2=lambda k=kind: k, Select2=lambda *_a: select_ok
            )
            for name, kind in kinds.items()
        }

    def FeatureByName(self, name: str) -> Any:  # noqa: N802
        return self._features.get(name)

    def ClearSelection2(self, _all: bool) -> None:  # noqa: N802
        self.calls.append("clear")

    def GraphicsRedraw2(self) -> None:  # noqa: N802
        self.redraws += 1

    def BlankRefGeom(self) -> None:  # noqa: N802
        self.calls.append("BlankRefGeom")

    def UnBlankRefGeom(self) -> None:  # noqa: N802
        self.calls.append("UnBlankRefGeom")

    def BlankSketch(self) -> None:  # noqa: N802
        self.calls.append("BlankSketch")

    def UnblankSketch(self) -> None:  # noqa: N802
        self.calls.append("UnblankSketch")


class _Harness(SolidWorksSelectionMixin):
    def __init__(self, model: Any) -> None:
        self.currentModel = model
        self.swApp = None

    def _handle_com_operation(self, name: str, operation: Any, *args: Any) -> Any:
        try:
            return AdapterResult(
                status=AdapterResultStatus.SUCCESS, data=operation(*args)
            )
        except Exception as exc:  # noqa: BLE001 - mirror the real adapter
            return AdapterResult(
                status=AdapterResultStatus.ERROR, error=f"Error in {name}: {exc}"
            )

    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001
            return default

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value


def test_types_are_switched_and_their_old_state_kept() -> None:
    harness = _Harness(_Model())

    changed = vis.set_display_types(harness, ["planes", "sketches"], False)

    assert changed == {
        "planes": {"before": True, "after": False},
        "sketches": {"before": True, "after": False},
    }
    toggles = harness.currentModel.Extension.toggles
    assert toggles[5] is False and toggles[196] is False and toggles[4] is True
    assert harness.currentModel.redraws == 1

    vis.restore_display_types(harness, changed | {"axes": {"before": None}})

    assert toggles[5] is True and toggles[196] is True


def test_a_toggle_solidworks_keeps_is_an_error() -> None:
    harness = _Harness(_Model(_Extension(stuck=5)))

    with pytest.raises(RuntimeError, match="SolidWorks kept planes shown"):
        vis.set_display_types(harness, ["planes"], False)


@pytest.mark.parametrize(
    ("name", "visible", "call"),
    [
        ("Plane1", False, "BlankRefGeom"),
        ("Axis1", True, "UnBlankRefGeom"),
        ("Sketch2", False, "BlankSketch"),
        ("Sketch2", True, "UnblankSketch"),
    ],
)
def test_a_feature_is_hidden_the_way_the_tree_hides_it(
    name: str, visible: bool, call: str
) -> None:
    harness = _Harness(_Model())

    done = vis.set_feature_visibility(harness, [name], visible)

    assert done[0]["visible"] is visible
    assert harness.currentModel.calls == ["clear", call, "clear"]


@pytest.mark.parametrize(
    ("model", "name", "error", "fragment"),
    [
        (_Model(), "Plane9", LookupError, "'Plane9' not found"),
        (_Model(), "Boss-Extrude1", ValueError, "use suppress_feature"),
        (_Model(select_ok=False), "Plane1", RuntimeError, "could not select 'Plane1'"),
    ],
)
def test_features_that_cannot_be_hidden(
    model: _Model, name: str, error: type[Exception], fragment: str
) -> None:
    with pytest.raises(error, match=None) as caught:
        vis.set_feature_visibility(_Harness(model), [name], False)
    assert fragment in str(caught.value)


def test_unknown_types_are_named() -> None:
    assert vis.unknown_types(["planes", "walls", "doors"]) == ["walls", "doors"]


async def test_the_adapter_method_does_names_and_types() -> None:
    harness = _Harness(_Model())

    result = await harness.set_visibility(["Plane1"], ["axes"], False)

    assert result.is_success, result.error
    assert result.data == {
        "visible": False,
        "features": [{"name": "Plane1", "type": "RefPlane", "visible": False}],
        "types": {"axes": {"before": True, "after": False}},
    }


@pytest.mark.parametrize(
    ("model", "names", "types", "fragment"),
    [
        (_Model(), [], [], "Give names, types or both"),
        (_Model(), [], ["walls"], "Unknown type(s) walls"),
        (None, ["Plane1"], [], "No active model"),
        (_Model(), ["Plane9"], [], "Feature 'Plane9' not found"),
    ],
)
async def test_the_adapter_method_refuses(
    model: Any, names: list[str], types: list[str], fragment: str
) -> None:
    result = await _Harness(model).set_visibility(names, types, False)

    assert result.is_error
    assert fragment in (result.error or "")
    assert not (result.error or "").startswith("Error in")
