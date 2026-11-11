"""The base adapter's default for ``select_edges``."""

from __future__ import annotations

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_an_adapter_without_it_says_so() -> None:
    result = await SolidWorksAdapter.select_edges(MockSolidWorksAdapter({}), {})

    assert result.error == "select_edges is not implemented by this adapter"
