"""``export_image`` takes ``hide`` and ``zoom_box_mm``."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
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


async def test_a_section_reaches_the_picture(mock_config: Any, tmp_path: Path) -> None:
    export = await _export_image(mock_config)

    result = await export(
        {
            "file_path": str(tmp_path / "latch.png"),
            "view_orientation": "front",
            "section": {"plane": " Front Plane "},
        }
    )

    assert result["status"] == "success", result
    assert result["data"]["section"] == {
        "plane": "Front Plane",
        "offset_mm": 0.0,
        "reverse": False,
        "removed": True,
    }
    assert "warning" not in result


async def test_an_unknown_section_plane_is_not_found(
    mock_config: Any, tmp_path: Path
) -> None:
    export = await _export_image(mock_config)

    result = await export(
        {"file_path": str(tmp_path / "x.png"), "section": {"plane": "Plane7"}}
    )

    assert result["error_type"] == "not_found"
    assert "no picture was taken" in result["message"]


@pytest.mark.parametrize(
    ("section", "fragment"),
    [
        ({"plane": "   "}, "needs a plane's name"),
        ({"plane": ""}, "section.plane"),
        ({"plane": "Front Plane", "offset": 2}, "section.offset"),
        ({"offset_mm": 2}, "section.plane"),
    ],
)
async def test_a_bad_section_is_invalid_input(
    mock_config: Any, tmp_path: Path, section: dict[str, Any], fragment: str
) -> None:
    export = await _export_image(mock_config)

    result = await export({"file_path": str(tmp_path / "x.png"), "section": section})

    assert result["error_type"] == "invalid_input"
    assert fragment in result["message"]


async def test_a_section_left_on_is_a_warning(mock_config: Any, tmp_path: Path) -> None:
    adapter = MockSolidWorksAdapter({})
    left_on = {"plane": "Front Plane", "offset_mm": 0.0, "reverse": False}
    adapter.export_image = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(
            status=AdapterResultStatus.SUCCESS,
            data={"section": {**left_on, "removed": False}},
        )
    )
    mcp = FastMCP("image")
    await register_export_tools(mcp, adapter, mock_config)
    export = next(t.fn for t in await mcp.list_tools() if t.name == "export_image")

    result = await export(
        {"file_path": str(tmp_path / "x.png"), "section": {"plane": "Front Plane"}}
    )

    assert result["status"] == "success"
    assert result["warning"].startswith(
        "The section on Front Plane could not be taken off"
    )
    sent = adapter.export_image.await_args.args[0]
    assert sent["section"] == left_on
