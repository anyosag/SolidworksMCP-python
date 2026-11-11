"""The base adapter's defaults for the outline and construction methods."""

from __future__ import annotations

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_an_adapter_without_them_says_so() -> None:
    """Called on the base class: an error naming the method, not a crash."""
    adapter = MockSolidWorksAdapter({})

    outlines = await SolidWorksAdapter.add_sketch_outlines(adapter, [])
    construction = await SolidWorksAdapter.set_sketch_construction(adapter, ["Line_1"])
    arc = await SolidWorksAdapter.add_arc(adapter, 0, 0, 1, 0, 0, 1, "cw")

    assert outlines.error == "add_sketch_outlines is not implemented by this adapter"
    assert construction.error == (
        "set_sketch_construction is not implemented by this adapter"
    )
    assert arc.error == "add_arc is not implemented by this adapter"
