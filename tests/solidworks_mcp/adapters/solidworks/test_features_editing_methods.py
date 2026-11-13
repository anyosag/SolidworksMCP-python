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


class _Measured(_Harness):
    """A harness whose part's volume reads as ``volumes``, one per read."""

    def __init__(self, volumes: list[float | None]) -> None:
        super().__init__(model=SimpleNamespace())
        self._volumes = list(volumes)
        self.reads = 0

    async def get_model_geometry_summary(self) -> AdapterResult[dict[str, Any]]:
        self.reads += 1
        volume = self._volumes.pop(0)
        if volume is None:
            return AdapterResult(status=AdapterResultStatus.ERROR, error="unreadable")
        return AdapterResult(
            status=AdapterResultStatus.SUCCESS, data={"volume_mm3": volume}
        )


_EDGES = {"edges_before": 1, "edges_given": 4, "edges_after": 4}


async def test_new_edges_report_the_volume_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    def edit(_adapter: Any, name: str, changes: dict[str, Any], _null: Any) -> Any:
        seen.append(changes)
        return {"feature": name, **_EDGES}

    monkeypatch.setattr(feature_editing, "edit_feature", edit)
    harness = _Measured([11980.0, 11965.3333])

    result = await harness.edit_feature("Chamfer1", {"edge_rules": {"side": "top"}})

    assert result.data["measured_change"] == {
        "volume_before_mm3": 11980.0,
        "volume_after_mm3": 11965.3333,
        "volume_delta_mm3": -14.6667,
    }
    assert result.data["edges_given"] == 4
    assert seen == [{"edge_rules": {"side": "top"}}]


@pytest.mark.parametrize(
    ("changes", "volumes", "reads"),
    [
        ({"radius": 2}, [], 0),  # no new edges: the volume isn't read
        ({"edges": "selection"}, [None], 1),  # unreadable before
        ({"edges": "selection"}, [100.0, None], 2),  # unreadable after
    ],
)
async def test_no_measured_change_without_both_volumes(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, Any],
    volumes: list[float | None],
    reads: int,
) -> None:
    monkeypatch.setattr(
        feature_editing, "edit_feature", lambda *_a: {"feature": "Fillet1"}
    )
    harness = _Measured(volumes)

    result = await harness.edit_feature("Fillet1", changes)

    assert result.is_success
    assert "measured_change" not in result.data
    assert harness.reads == reads


async def test_a_failed_edge_change_reads_the_volume_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_a: Any) -> Any:
        raise ValueError("No new edges for 'Fillet1', so it is unchanged: nothing")

    monkeypatch.setattr(feature_editing, "edit_feature", refuse)
    harness = _Measured([100.0])

    result = await harness.edit_feature("Fillet1", {"edges": "selection"})

    assert result.error == "No new edges for 'Fillet1', so it is unchanged: nothing"
    assert harness.reads == 1


async def test_without_a_model_new_edges_read_no_volume() -> None:
    harness = _Measured([])
    harness.currentModel = None

    result = await harness.edit_feature("Fillet1", {"edges": "selection"})

    assert result.error == "No active model"
    assert harness.reads == 0
