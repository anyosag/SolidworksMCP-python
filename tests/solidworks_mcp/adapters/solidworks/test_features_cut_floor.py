"""A blind cut records its floor area; a through cut and a drafted one don't."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import cut_check

from .test_features_cut_direction import _cut, _Part


class _PartWithSketch(_Part):
    """The part, whose sketch can be looked up by name."""

    def __init__(self) -> None:
        super().__init__(along=9.05, against=None)
        self.sketch_feature = SimpleNamespace(name="Sketch3")

    def FeatureByName(self, name: str) -> Any:  # noqa: N802
        return self.sketch_feature if name == "Sketch3" else super().FeatureByName(name)


@pytest.mark.parametrize(
    ("fields", "measured"),
    [
        ({}, True),
        ({"end_condition": "ThroughAll"}, False),
        ({"draft_angle": 2.0}, False),
    ],
)
async def test_only_a_straight_blind_cut_measures_its_floor(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any], measured: bool
) -> None:
    part = _PartWithSketch()
    seen: list[Any] = []

    def measure(_adapter: Any, feature: Any, sketch_feature: Any) -> float:
        seen.append((feature.Name, sketch_feature))
        return 4.525

    monkeypatch.setattr(cut_check, "measure_floor", measure)

    _adapter, result = await _cut(part, reverse_direction=True, **fields)

    assert result.is_success, result.error
    floor = result.data.parameters["floor_area_mm2"]
    if measured:
        assert floor == 4.525
        assert seen == [("Cut-Extrude1", part.sketch_feature)]
    else:
        assert floor is None
        assert seen == []
