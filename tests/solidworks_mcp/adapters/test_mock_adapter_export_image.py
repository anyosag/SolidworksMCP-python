"""The mock reports ``export_image``'s zoom the way the real adapter does."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


@pytest.fixture
async def adapter() -> MockSolidWorksAdapter:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_part()
    return mock


@pytest.mark.parametrize(
    ("payload", "view", "zoomed"),
    [
        ({}, "current", False),  # the adapter's own default
        ({"view_orientation": "Current"}, "current", False),
        ({"view_orientation": "Isometric"}, "isometric", True),
        ({"view_orientation": "current", "zoom_to_fit": True}, "current", True),
        ({"view_orientation": "front", "zoom_to_fit": False}, "front", False),
    ],
)
async def test_current_keeps_the_zoom(
    adapter: MockSolidWorksAdapter,
    tmp_path: Path,
    payload: dict[str, Any],
    view: str,
    zoomed: bool,
) -> None:
    result = await adapter.export_image(
        {"file_path": str(tmp_path / "shot.png")} | payload
    )

    assert result.is_success
    assert result.data["view"] == view
    assert result.data["zoomed_to_fit"] is zoomed
