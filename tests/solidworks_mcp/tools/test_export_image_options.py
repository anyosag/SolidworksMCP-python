"""``export_image`` takes ``hide`` and ``zoom_box_mm``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.export import register_export_tools


async def _export_image(config: Any) -> Any:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    mcp = FastMCP("image")
    await register_export_tools(mcp, adapter, config)
    return next(t.fn for t in await mcp.list_tools() if t.name == "export_image")


async def test_the_options_reach_the_picture(mock_config: Any, tmp_path: Path) -> None:
    export = await _export_image(mock_config)

    result = await export(
        {
            "file_path": str(tmp_path / "deck.png"),
            "hide": ["planes", "sketches"],
            "zoom_box_mm": [0, 0, 0, 30, 30, 5],
        }
    )

    assert result["status"] == "success", result
    assert result["data"]["hidden"] == ["planes", "sketches"]
    assert result["data"]["zoom_box_mm"] == [0, 0, 0, 30, 30, 5]


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"zoom_box_mm": [0, 0, 0, 1, 1, 1], "zoom_to_fit": True}, "can't both apply"),
        ({"zoom_box_mm": [1, 2, 3, 1, 2, 3]}, "two different corners"),
        ({"zoom_box_mm": [0, 0, 0, 1, 1]}, "at least 6"),
        ({"hide": ["ghosts"]}, "hide.0"),
    ],
)
async def test_impossible_options_are_invalid_input(
    mock_config: Any, tmp_path: Path, arguments: dict[str, Any], fragment: str
) -> None:
    export = await _export_image(mock_config)

    result = await export({"file_path": str(tmp_path / "x.png"), **arguments})

    assert result["error_type"] == "invalid_input"
    assert fragment in result["message"]
