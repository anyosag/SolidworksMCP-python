"""``delete_feature`` names a feature's absorbed sketch and can delete it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import features
from solidworks_mcp.adapters.solidworks.features import (
    _absorbed_sketches,
    _delete_feature_impl,
)


class _Sub:
    """One sub-feature in the chain ``GetFirstSubFeature`` starts."""

    def __init__(self, name: str, kind: str, after: _Sub | None = None) -> None:
        self.Name, self._kind, self._after = name, kind, after

    def GetTypeName2(self) -> str:  # noqa: N802
        return self._kind

    def GetNextSubFeature(self) -> _Sub | None:  # noqa: N802
        return self._after


def _adapter(monkeypatch: pytest.MonkeyPatch) -> PyWin32Adapter:
    """A PyWin32Adapter with no COM behind it (as in test_features.py)."""
    target = "solidworks_mcp.adapters.pywin32_adapter"
    monkeypatch.setattr(f"{target}.PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(f"{target}.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        f"{target}.pywintypes", SimpleNamespace(com_error=RuntimeError), raising=False
    )
    monkeypatch.setattr(
        f"{target}._ComSessionCoordinator",
        lambda _adapter: SimpleNamespace(),
        raising=False,
    )
    return PyWin32Adapter({})


def test_the_sketches_under_a_feature_are_its_absorbed_ones() -> None:
    chain = _Sub(
        "Sketch4",
        "ProfileFeature",
        _Sub("Note1", "Annotation", _Sub("3DSketch1", "3DProfileFeature")),
    )
    cut = SimpleNamespace(GetFirstSubFeature=lambda: chain)
    adapter = SimpleNamespace(
        _attempt=lambda fn, default=None: _safe(fn, default),
    )

    assert _absorbed_sketches(adapter, cut) == ["Sketch4", "3DSketch1"]
    assert _absorbed_sketches(adapter, SimpleNamespace()) == []


def _safe(fn: Any, default: Any) -> Any:
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


@pytest.mark.parametrize(("delete_absorbed", "options"), [(False, 1), (True, 3)])
def test_delete_absorbed_adds_swdelete_absorbed(
    monkeypatch: pytest.MonkeyPatch, delete_absorbed: bool, options: int
) -> None:
    adapter = _adapter(monkeypatch)
    adapter.currentModel = MagicMock()
    cut = SimpleNamespace(
        Select2=lambda *_a: True,
        GetFirstSubFeature=lambda: _Sub("Sketch4", "ProfileFeature"),
    )
    adapter.currentModel.FeatureByName.side_effect = [cut, None]
    adapter.currentModel.FeatureManager.GetFeatureCount.side_effect = [7, 6]

    result = _delete_feature_impl(adapter, "Cut-Extrude1", delete_absorbed)

    assert result.is_success, result.error
    adapter.currentModel.Extension.DeleteSelection2.assert_called_once_with(options)
    assert result.data["absorbed_sketches"] == ["Sketch4"]


@pytest.mark.parametrize(
    ("removed", "left"),
    # removed_features is in tree order: the sketch sits above its cut.
    [(["Cut-Extrude1"], ["Sketch4"]), (["Sketch4", "Cut-Extrude1"], [])],
)
async def test_the_sketches_left_are_those_still_in_the_tree(
    monkeypatch: pytest.MonkeyPatch, removed: list[str], left: list[str]
) -> None:
    adapter = _adapter(monkeypatch)
    adapter.currentModel = MagicMock()
    tree = [{"name": n} for n in ("Sketch4", "Cut-Extrude1", "Fillet1")]
    adapter.list_features = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            AdapterResult(status=AdapterResultStatus.SUCCESS, data=tree),
            AdapterResult(
                status=AdapterResultStatus.SUCCESS,
                data=[f for f in tree if f["name"] not in removed],
            ),
        ]
    )
    calls: list[tuple[Any, ...]] = []

    def fake_delete(*args: Any) -> AdapterResult[dict[str, Any]]:
        calls.append(args)
        return AdapterResult(
            status=AdapterResultStatus.SUCCESS,
            data={"deleted": "Cut-Extrude1", "absorbed_sketches": ["Sketch4"]},
        )

    monkeypatch.setattr(features, "_delete_feature_impl", fake_delete)

    result = await adapter.delete_feature("Cut-Extrude1", True)

    assert calls[0][1:] == ("Cut-Extrude1", True)
    assert result.data["removed_features"] == removed
    assert result.data["absorbed_sketches_left"] == left
