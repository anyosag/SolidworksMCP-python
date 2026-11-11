"""The base adapter's default for ``check_wall_thickness``."""

from __future__ import annotations

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_an_adapter_without_it_says_so() -> None:
    result = await SolidWorksAdapter.check_wall_thickness(MockSolidWorksAdapter({}))

    assert result.error == "check_wall_thickness is not implemented by this adapter"
