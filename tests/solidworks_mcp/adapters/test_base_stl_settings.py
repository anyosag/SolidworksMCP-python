"""The base adapter's default for ``export_stl_with_settings``."""

from __future__ import annotations

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_an_adapter_without_it_says_so() -> None:
    result = await SolidWorksAdapter.export_stl_with_settings(
        MockSolidWorksAdapter({}), "o.stl", {"units": "mm"}
    )

    assert result.error == "export_stl_with_settings is not implemented by this adapter"
