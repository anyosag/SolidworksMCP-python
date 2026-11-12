"""The circuit breaker forwards the editing methods."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("edit_feature", ("Cut1", {"depth": 2})),
        ("set_rollback", ("Cut1", None)),
        ("edit_sketch", ("Sketch1",)),
        ("delete_sketch_entities", (["Line_1"],)),
        ("delete_all_sketch_entities", ()),
    ],
)
async def test_the_breaker_passes_the_arguments(method: str, args: tuple) -> None:
    inner = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    setattr(inner, method, AsyncMock(return_value=ok))

    assert (await getattr(CircuitBreakerAdapter(adapter=inner), method)(*args)) is ok
    getattr(inner, method).assert_awaited_once_with(*args)
