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
