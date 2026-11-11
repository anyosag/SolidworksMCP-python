"""The mock adapter's planes, arc direction, outlines and construction geometry.

Each refusal matches the live adapter's (``adapters/solidworks/sketch.py``),
so a test that passes on the mock does not fail live on the same input.
"""

from __future__ import annotations

from typing import Any

import pytest

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.adapters.solidworks import sketch


@pytest.fixture
async def adapter() -> MockSolidWorksAdapter:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_part()
    return mock


def _line(x1: float, y1: float, x2: float, y2: float) -> dict[str, Any]:
    return {"type": "line", "start": [x1, y1], "end": [x2, y2]}


async def test_a_plane_not_in_the_part_is_refused(
    adapter: MockSolidWorksAdapter,
) -> None:
    result = await adapter.create_sketch("Plane3")

    assert result.is_error
    assert result.error == (
        "Plane 'Plane3' not found in the part. Use Front, Top or Right, or a "
        "plane made by create_reference_plane (list_features names them)"
    )
    assert "not found in the part" in (
        sketch._create_sketch_impl(_NoPlanes(), "Plane3").error or ""
    )


class _NoPlanes:
    """A live-adapter stand-in whose part has no planes, for the shared wording."""

    currentModel = type(
        "Model",
        (),
        {
            "FeatureByName": staticmethod(lambda _name: None),
            "Extension": type(
                "Ext", (), {"SelectByID2": staticmethod(lambda *_a: False)}
            )(),
        },
    )()

    def _handle_com_operation(self, _name: str, callback: Any) -> Any:
        from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus

        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt_with_error(self, callback: Any) -> Any:
        return callback(), None

    def _attempt(self, callback: Any, default: Any = None) -> Any:
        try:
            return callback()
        except Exception:
            return default


async def test_default_planes_report_their_axes(adapter: MockSolidWorksAdapter) -> None:
    result = await adapter.create_sketch("Top")

    assert result.is_success
    assert result.metadata is not None
    assert result.metadata["plane"] == "Top Plane"
    assert result.metadata["axes"]["normal"] == [0.0, 1.0, 0.0]


async def test_a_reference_plane_is_accepted_without_axes(
    adapter: MockSolidWorksAdapter,
) -> None:
    plane = await adapter.create_reference_plane(reference="Front Plane", offset=5.0)

    result = await adapter.create_sketch(plane.data["name"])

    assert result.is_success
    assert result.metadata == {"plane": plane.data["name"], "axes": None}


async def test_an_arc_direction_is_checked(adapter: MockSolidWorksAdapter) -> None:
    await adapter.create_sketch("Front")

    assert (await adapter.add_arc(0, 0, 5, 0, 0, 5, "cw")).is_success
    wrong = await adapter.add_arc(0, 0, 5, 0, 0, 5, "up")
    assert wrong.error == "direction must be 'ccw' or 'cw', not 'up'"


async def test_outlines_get_distinct_ids(adapter: MockSolidWorksAdapter) -> None:
    await adapter.create_sketch("Front")
    square = [
        _line(0, 0, 1, 0),
        _line(1, 0, 1, 1),
        _line(1, 1, 0, 1),
        _line(0, 1, 0, 0),
    ]
    arc = {"type": "arc", "center": [0, 0], "start": [2, 0], "end": [0, 2]}

    result = await adapter.add_sketch_outlines(
        [
            {"segments": square * 50, "construction": False},
            {"segments": [arc], "construction": True},
        ]
    )

    assert result.is_success
    data = result.data or {}
    ids = data["outlines"][0]["ids"] + data["outlines"][1]["ids"]
    assert len(ids) == len(set(ids)) == 201
    assert data["outlines"][1] == {"ids": [ids[-1]], "construction": True}
    assert ids[-1].startswith("Arc_")
    assert (data["line_count"], data["arc_count"]) == (200, 1)


async def test_outline_ids_skip_ids_already_taken(
    adapter: MockSolidWorksAdapter,
) -> None:
    await adapter.create_sketch("Front")
    adapter._sketch_entity_ids.add("Line_2")  # the next free number is taken

    result = await adapter.add_sketch_outlines(
        [{"segments": [_line(0, 0, 1, 0)], "construction": False}]
    )

    assert (result.data or {})["outlines"][0]["ids"] == ["Line_3"]


@pytest.mark.parametrize(
    ("outlines", "message"),
    [
        ([{"segments": []}], "outlines contain no segments"),
        (
            [{"segments": [_line(0, 0, 1, 0)] * 2001}],
            "2001 segments in one call; the most is 2000",
        ),
    ],
)
async def test_outlines_refused_like_the_live_adapter(
    adapter: MockSolidWorksAdapter, outlines: list[dict[str, Any]], message: str
) -> None:
    await adapter.create_sketch("Front")

    result = await adapter.add_sketch_outlines(outlines)

    assert message in (result.error or "")


async def test_outlines_and_construction_need_an_open_sketch() -> None:
    mock = MockSolidWorksAdapter({})
    await mock.connect()

    assert (await mock.add_sketch_outlines([])).error == "No active sketch"
    assert (await mock.set_sketch_construction(["Line_1"])).error == "No active sketch"


async def test_construction_counts_a_rectangle_as_four_lines(
    adapter: MockSolidWorksAdapter,
) -> None:
    await adapter.create_sketch("Front")
    rectangle = (await adapter.add_rectangle(0, 0, 10, 5)).data
    line = (await adapter.add_line(0, 0, 5, 5)).data

    result = await adapter.set_sketch_construction([rectangle, line])

    assert result.data == {
        "entity_ids": [rectangle, line],
        "segment_count": 5,
        "construction": True,
    }
    missing = await adapter.set_sketch_construction(["Line_404"])
    assert missing.error == "Sketch entity Line_404 not found in the open sketch"
