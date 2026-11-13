"""The mock's ``measure_clearance``: canned boxes where ``insert_component`` put them."""

from __future__ import annotations

import pytest

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def _assembly(*origins: tuple[float, float, float]) -> MockSolidWorksAdapter:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_assembly()
    for x, y, z in origins:
        await adapter.insert_component("C:/parts/block.sldprt", x, y, z)
    return adapter


async def test_two_cubes_a_quarter_millimetre_apart() -> None:
    adapter = await _assembly((0, 0, 0), (10.25, 0, 0))

    result = await adapter.measure_clearance("component-1", "component-2")

    assert result.is_success, result.error
    data = result.data
    assert data["clearance_mm"] == pytest.approx(0.25)
    assert data["touching"] is False
    assert data["point_a_mm"] == [10.0, 5.0, 5.0]
    assert data["point_b_mm"] == [10.25, 5.0, 5.0]
    assert data["face_b"] == {
        "kind": "plane",
        "box_mm": [10.25, 0.0, 0.0, 20.25, 10.0, 10.0],
    }
    assert (data["pairs_checked"], data["pairs_total"]) == (1, 1)


async def test_a_component_moved_later_is_measured_where_it_is() -> None:
    adapter = await _assembly((0, 0, 0), (50, 0, 0))

    await adapter.set_component_transform("component-2", [10.5, 0, 0])
    result = await adapter.measure_clearance("component-1", "component-2")

    assert result.data["clearance_mm"] == pytest.approx(0.5)


async def test_canned_boxes_overlapping_touch() -> None:
    adapter = await _assembly((0, 0, 0), (0, 0, 0))
    adapter.component_boxes_mm["component-2"] = [9.0, 0.0, 0.0, 20.0, 10.0, 10.0]

    result = await adapter.measure_clearance("component-2", "component-1")

    assert result.data["clearance_mm"] == 0.0
    assert result.data["touching"] is True
    assert result.data["point_a_mm"] == result.data["point_b_mm"]


async def test_a_gap_below_the_other_component() -> None:
    adapter = await _assembly((0, 0, 0), (0, 0, -12))

    result = await adapter.measure_clearance("component-1", "component-2")

    assert result.data["clearance_mm"] == pytest.approx(2.0)
    assert result.data["point_a_mm"][2] == 0.0
    assert result.data["point_b_mm"][2] == -2.0


async def test_the_refusals_match_the_real_adapter() -> None:
    adapter = await _assembly((0, 0, 0), (20, 0, 0))

    same = await adapter.measure_clearance("component-1", "component-1")
    unknown = await adapter.measure_clearance("component-1", "pin-1")
    adapter.component_boxes_mm["component-2"] = None
    bodiless = await adapter.measure_clearance("component-1", "component-2")

    assert same.error == (
        "Invalid request: component_a and component_b are both 'component-1'; "
        "give two different components."
    )
    assert unknown.error == (
        "Component(s) not found: pin-1. The assembly holds: component-1, component-2."
    )
    assert bodiless.error.startswith(
        "Invalid request: component_b 'component-2' holds no solid body"
    )


async def test_it_needs_an_assembly() -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()

    nothing = await adapter.measure_clearance("a-1", "b-1")
    await adapter.create_part()
    part = await adapter.measure_clearance("a-1", "b-1")

    assert nothing.error == "No active model"
    assert part.error == (
        "Invalid request: measure_clearance measures between components of an "
        "assembly, and the active document is a part; activate the assembly first."
    )
