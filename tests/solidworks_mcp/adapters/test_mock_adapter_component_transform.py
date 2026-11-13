"""The mock's component placement: insert's fixed state and set_component_transform."""

from __future__ import annotations

import pytest

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter

_QUARTER_Y = [[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]


@pytest.fixture
async def assembly() -> MockSolidWorksAdapter:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_assembly()
    return mock


async def test_the_first_component_is_fixed_unless_asked(assembly) -> None:
    first = await assembly.insert_component("a.sldprt")
    second = await assembly.insert_component("b.sldprt", 10, 0, 0)
    floating = MockSolidWorksAdapter({})
    await floating.connect()
    await floating.create_assembly()
    loose = await floating.insert_component("a.sldprt", fixed=False)

    assert first.data["placement"]["fixed"] is True
    assert second.data["placement"]["fixed"] is False
    assert second.data["placement"]["origin_mm"] == [10.0, 0.0, 0.0]
    assert loose.data["placement"]["fixed"] is False


async def test_a_component_is_moved_turned_and_fixed(assembly) -> None:
    await assembly.insert_component("a.sldprt")
    await assembly.insert_component("b.sldprt")

    moved = await assembly.set_component_transform("component-2", [0, 137, 0])
    turned = await assembly.set_component_transform(
        "component-2", None, _QUARTER_Y, fixed=True
    )
    again = await assembly.set_component_transform("component-2")

    assert moved.data["origin_mm"] == [0.0, 137.0, 0.0]
    assert (moved.data["placed"], moved.data["moved"]) == (True, True)
    assert turned.data["origin_mm"] == [0.0, 137.0, 0.0]
    assert turned.data["rotation"] == _QUARTER_Y
    assert turned.data["fixed"] is True
    assert again.data["moved"] is False


async def test_mates_on_a_component_are_counted(assembly) -> None:
    await assembly.insert_component("a.sldprt")
    await assembly.insert_component("b.sldprt")
    await assembly.add_mate("component-1", "component-2")

    placed = await assembly.set_component_transform("component-2", [5, 0, 0])

    assert placed.data["mates"] == 1


async def test_placing_needs_an_assembly_and_a_known_component(assembly) -> None:
    await assembly.insert_component("a.sldprt")
    part = MockSolidWorksAdapter({})
    await part.connect()
    await part.create_part()

    missing = await assembly.set_component_transform("ghost-1", [0, 0, 0])
    wrong_doc = await part.set_component_transform("component-1", [0, 0, 0])

    assert missing.error == (
        "Component(s) not found: ghost-1. The assembly holds: component-1."
    )
    assert wrong_doc.error == "set_component_transform requires an assembly document"


async def test_an_untracked_component_starts_at_the_origin() -> None:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_assembly()
    mock._components.append("legacy-1")

    placed = await mock.set_component_transform("legacy-1", [1, 2, 3])

    assert placed.data["origin_mm"] == [1.0, 2.0, 3.0]
    assert placed.data["fixed"] is False
