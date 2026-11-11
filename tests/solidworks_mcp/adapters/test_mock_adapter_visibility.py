"""The mock's show/hide, absorbed sketches and reversed patterns."""

from __future__ import annotations

import pytest

from solidworks_mcp.adapters.base import ExtrusionParameters
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


@pytest.fixture
async def part() -> MockSolidWorksAdapter:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_part()
    return mock


async def test_types_remember_their_state(part: MockSolidWorksAdapter) -> None:
    first = await part.set_visibility(types=["planes"], visible=False)
    second = await part.set_visibility(types=["planes"], visible=True)

    assert (first.data or {})["types"]["planes"] == {"before": True, "after": False}
    assert (second.data or {})["types"]["planes"] == {"before": False, "after": True}


async def test_names_of_every_hideable_kind(part: MockSolidWorksAdapter) -> None:
    axis = (await part.create_axis("x")).data["name"]
    plane = (await part.create_reference_plane(reference="Top Plane", offset=5)).data[
        "name"
    ]
    sketch = (await part.create_sketch("Front")).data["sketch_name"]

    result = await part.set_visibility(names=[axis, plane, sketch], visible=False)

    assert [f["type"] for f in (result.data or {})["features"]] == [
        "RefAxis",
        "RefPlane",
        "ProfileFeature",
    ]
    shown = await part.set_visibility(names=[axis], visible=True)
    assert (shown.data or {})["features"][0]["visible"] is True


async def test_visibility_refusals(part: MockSolidWorksAdapter) -> None:
    await part.create_sketch("Top")
    await part.add_rectangle(0, 0, 5, 5)
    await part.exit_sketch()
    boss = (await part.create_extrusion(ExtrusionParameters(depth=2))).data.name

    assert (
        await part.set_visibility()
    ).error == "Give names, types or both to show or hide."
    assert "Unknown type(s) walls" in (
        (await part.set_visibility(types=["walls"])).error or ""
    )
    assert "'Plane9' not found" in (
        (await part.set_visibility(names=["Plane9"])).error or ""
    )
    assert "use suppress_feature" in (
        (await part.set_visibility(names=[boss])).error or ""
    )
    empty = MockSolidWorksAdapter({})
    await empty.connect()
    assert (await empty.set_visibility(types=["planes"])).error == "No active model"


async def test_a_deleted_feature_keeps_its_sketch_unless_asked(
    part: MockSolidWorksAdapter,
) -> None:
    sketch = (await part.create_sketch("Top")).data["sketch_name"]
    await part.add_rectangle(0, 0, 5, 5)
    await part.exit_sketch()
    boss = await part.create_extrusion(ExtrusionParameters(depth=2, sketch_name=sketch))

    kept = await part.delete_feature(boss.data.name)

    assert (kept.data or {})["absorbed_sketches_left"] == [sketch]
    assert sketch in part._sketches

    again = await part.create_extrusion(
        ExtrusionParameters(depth=2, sketch_name=sketch)
    )
    gone = await part.delete_feature(again.data.name, delete_absorbed=True)

    assert (gone.data or {})["absorbed_sketches_left"] == []
    assert sketch in (gone.data or {})["removed_features"]
    assert sketch not in part._sketches


async def test_a_reversed_pattern_says_so(part: MockSolidWorksAdapter) -> None:
    axis = (await part.create_axis("y")).data["name"]

    result = await part.pattern_circular(["Cut1"], axis, 3, 60.0, False, True)

    assert (result.data or {})["reverse_direction"] is True
    assert (result.data or {})["equal_spacing"] is False
