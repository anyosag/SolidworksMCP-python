"""The mock's ``export_image`` reports hidden types and a zoom box as the real one."""

from __future__ import annotations

from pathlib import Path

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def _part() -> MockSolidWorksAdapter:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    return adapter


async def test_hidden_types_and_the_zoom_box_are_reported(tmp_path: Path) -> None:
    adapter = await _part()

    result = await adapter.export_image(
        {
            "file_path": str(tmp_path / "a.png"),
            "view_orientation": "isometric",
            "hide": ["sketches", "planes"],
            "zoom_box_mm": [0, 0, 0, 1, 1, 1],
        }
    )

    assert result.is_success
    assert result.data["hidden"] == ["planes", "sketches"]
    assert result.data["zoom_box_mm"] == [0, 0, 0, 1, 1, 1]
    assert result.data["zoomed_to_fit"] is False


async def test_an_unknown_type_is_refused(tmp_path: Path) -> None:
    adapter = await _part()

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "a.png"), "hide": ["ghosts"]}
    )

    assert result.error == "Unknown display type(s) to hide: ghosts"
    assert not (tmp_path / "a.png").exists()


async def test_a_section_is_recorded_and_taken_off(tmp_path: Path) -> None:
    adapter = await _part()

    result = await adapter.export_image(
        {
            "file_path": str(tmp_path / "a.png"),
            "section": {"plane": "Front Plane", "offset_mm": 3, "reverse": True},
        }
    )
    plain = await adapter.export_image({"file_path": str(tmp_path / "b.png")})

    assert result.data["section"] == {
        "plane": "Front Plane",
        "offset_mm": 3.0,
        "reverse": True,
        "removed": True,
    }
    assert plain.data["section"] is None


async def test_a_reference_plane_can_cut_the_picture(tmp_path: Path) -> None:
    adapter = await _part()
    await adapter.create_reference_plane("Front Plane", offset=5.0)

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "a.png"), "section": {"plane": "Plane1"}}
    )

    assert result.is_success, result.error
    assert result.data["section"]["offset_mm"] == 0.0


async def test_an_unknown_section_plane_takes_no_picture(tmp_path: Path) -> None:
    adapter = await _part()

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "a.png"), "section": {"plane": "Plane7"}}
    )

    assert result.error == (
        "Section plane not found: the model has no plane named 'Plane7', so no "
        "picture was taken. Use a plane's name from list_features, such as Front "
        "Plane."
    )
    assert not (tmp_path / "a.png").exists()
