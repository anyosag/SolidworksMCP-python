"""The base adapter's default for ``measure_clearance``."""

from __future__ import annotations

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_an_adapter_without_it_says_so() -> None:
    result = await SolidWorksAdapter.measure_clearance(
        MockSolidWorksAdapter({}), "a-1", "b-1"
    )

    assert result.error == "measure_clearance is not implemented by this adapter"
