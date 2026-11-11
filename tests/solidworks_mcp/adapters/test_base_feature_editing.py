"""The base adapter's defaults for the editing methods."""

from __future__ import annotations

import pytest

from solidworks_mcp.adapters.base import SolidWorksAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("edit_feature", ("Cut1", {"depth": 2})),
        ("set_rollback", ()),
        ("edit_sketch", ("Sketch1",)),
        ("delete_sketch_entities", (["Line_1"],)),
    ],
)
async def test_an_adapter_without_them_says_so(method: str, args: tuple) -> None:
    result = await getattr(SolidWorksAdapter, method)(MockSolidWorksAdapter({}), *args)

    assert result.error == f"{method} is not implemented by this adapter"
