"""The base adapter's default for ``check_printability``."""

from __future__ import annotations

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_an_adapter_without_it_says_so() -> None:
    result = await SolidWorksAdapter.check_printability(MockSolidWorksAdapter({}), "z")

    assert result.error == "check_printability is not implemented by this adapter"
