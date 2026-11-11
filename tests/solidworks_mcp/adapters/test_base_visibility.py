"""The base adapter's default for ``set_visibility``."""

from __future__ import annotations

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_an_adapter_without_it_says_so() -> None:
    result = await SolidWorksAdapter.set_visibility(
        MockSolidWorksAdapter({}), ["Plane1"], None, False
    )

    assert result.error == "set_visibility is not implemented by this adapter"
