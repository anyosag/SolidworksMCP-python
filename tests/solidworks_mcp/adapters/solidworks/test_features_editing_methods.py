"""The adapter methods behind edit_feature, set_rollback and sketch editing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import feature_editing
from solidworks_mcp.adapters.solidworks.features import SolidWorksFeaturesMixin
from solidworks_mcp.adapters.solidworks.sketch import SolidWorksSketchMixin


class _Harness(SolidWorksFeaturesMixin, SolidWorksSketchMixin):
    def __init__(self, model: Any = None, sketch_manager: Any = None) -> None:
        self.currentModel = model
        self.currentSketchManager = sketch_manager

    def _handle_com_operation(self, name: str, operation: Any, *args: Any) -> Any:
        try:
            return AdapterResult(
                status=AdapterResultStatus.SUCCESS, data=operation(*args)
            )
        except Exception as exc:  # noqa: BLE001 - mirror the real adapter
            return AdapterResult(
                status=AdapterResultStatus.ERROR, error=f"Error in {name}: {exc}"
            )


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("edit_feature", ("Cut1", {"depth": 2})),
        ("set_rollback", ("Cut1", None)),
        ("edit_sketch", ("Sketch1",)),
    ],
)
async def test_no_model_is_said_plainly(method: str, args: tuple[Any, ...]) -> None:
    result = await getattr(_Harness(), method)(*args)

    assert result.error == "No active model"


async def test_errors_lose_the_operation_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_a: Any) -> Any:
        raise LookupError("Feature 'Cut9' not found; list_features names them.")

    for name in (
        "edit_feature",
        "set_rollback",
        "open_sketch",
        "delete_sketch_entities",
        "delete_all_sketch_entities",
    ):
        monkeypatch.setattr(feature_editing, name, refuse)
    harness = _Harness(model=SimpleNamespace(), sketch_manager=object())

    for result in (
        await harness.edit_feature("Cut9", {"depth": 2}),
        await harness.set_rollback(after="Cut9"),
        await harness.edit_sketch("Cut9"),
        await harness.delete_sketch_entities(["Line_1"]),
        await harness.delete_all_sketch_entities(),
    ):
        assert result.error == "Feature 'Cut9' not found; list_features names them."


async def test_success_passes_the_reply_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        feature_editing,
        "set_rollback",
        lambda *_a: {"position": "the end", "rolled_back": []},
    )

    result = await _Harness(model=SimpleNamespace()).set_rollback()

    assert result.data == {"position": "the end", "rolled_back": []}


async def test_deleting_entities_needs_an_open_sketch() -> None:
    harness = _Harness(model=SimpleNamespace())

    assert (await harness.delete_sketch_entities(["Line_1"])).error == (
        "No active sketch"
    )
    assert (await harness.delete_all_sketch_entities()).error == "No active sketch"
