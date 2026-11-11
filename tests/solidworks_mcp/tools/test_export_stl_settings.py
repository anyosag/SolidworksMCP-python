"""``export_stl`` with mesh settings for this file only.

From the Cellvis dish rack: printing needed a finer mesh than the user's STL
options, and the only way was to change them in SolidWorks by hand.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.export import ExportStlInput, register_export_tools


async def _export_stl(adapter: Any, config: Any) -> Any:
    mcp = FastMCP("stl")
    await register_export_tools(mcp, adapter, config)
    return next(t.fn for t in await mcp.list_tools() if t.name == "export_stl")


async def _part() -> MockSolidWorksAdapter:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    return adapter


async def test_mesh_settings_go_with_the_export(mock_config: Any) -> None:
    adapter = await _part()
    export = await _export_stl(adapter, mock_config)

    result = await export(
        {"file_path": "C:/out/rack.stl", "deviation_mm": 0.01, "angle_deg": 5}
    )

    assert result["status"] == "success", result
    assert result["export"]["mesh"] == {
        "applied": ["resolution custom", "deviation 0.01 mm", "angle 5 deg"],
        "restored": True,
    }
    assert "warning" not in result


async def test_options_not_put_back_are_a_warning(mock_config: Any) -> None:
    adapter = await _part()
    adapter.export_stl_with_settings = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(
            status=AdapterResultStatus.SUCCESS,
            data={"mesh": {"applied": ["units mm"], "restored": False}},
        )
    )
    export = await _export_stl(adapter, mock_config)

    result = await export({"file_path": "C:/out/rack.stl", "units": "mm"})

    assert result["status"] == "success"
    assert "could not all be put back" in result["warning"]


async def test_without_settings_the_users_options_are_used(mock_config: Any) -> None:
    adapter = await _part()
    adapter.export_stl_with_settings = AsyncMock()  # type: ignore[method-assign]
    export = await _export_stl(adapter, mock_config)

    result = await export({"file_path": "C:/out/rack.stl"})

    assert result["status"] == "success"
    assert "mesh" not in result["export"]
    adapter.export_stl_with_settings.assert_not_awaited()


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ({"resolution": "coarse", "deviation_mm": 0.1}, "need resolution 'custom'"),
        ({"angle_deg": 0}, "greater than 0"),
        ({"units": "furlong"}, "Input should be"),
    ],
)
async def test_impossible_settings_are_invalid_input(
    mock_config: Any, arguments: dict[str, Any], fragment: str
) -> None:
    export = await _export_stl(await _part(), mock_config)

    result = await export({"file_path": "C:/out/rack.stl", **arguments})

    assert result["error_type"] == "invalid_input"
    assert fragment in result["message"]


async def test_an_adapter_that_cannot_set_them_says_so(mock_config: Any) -> None:
    class _Plain:
        async def export_file(self, *_a: Any) -> AdapterResult[None]:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=None)

    export = await _export_stl(_Plain(), mock_config)

    result = await export({"file_path": "C:/out/rack.stl", "binary": True})

    assert result["error_type"] == "not_supported"
    assert ExportStlInput(file_path="a.stl").mesh_settings() == {}
