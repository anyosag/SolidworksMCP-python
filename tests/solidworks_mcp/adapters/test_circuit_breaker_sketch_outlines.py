"""The circuit breaker forwards the outline, construction and arc-direction calls."""

from __future__ import annotations

from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_the_breaker_passes_every_argument_through() -> None:
    inner = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={"done": True})
    inner.add_sketch_outlines = AsyncMock(return_value=ok)  # type: ignore[method-assign]
    inner.set_sketch_construction = AsyncMock(return_value=ok)  # type: ignore[method-assign]
    inner.add_arc = AsyncMock(return_value=ok)  # type: ignore[method-assign]
    breaker = CircuitBreakerAdapter(adapter=inner)
    outlines = [{"segments": [], "construction": False}]

    assert (await breaker.add_sketch_outlines(outlines)) is ok
    assert (await breaker.set_sketch_construction(["Line_1"], False)) is ok
    assert (await breaker.add_arc(0, 0, 1, 0, 0, 1, "cw")) is ok

    inner.add_sketch_outlines.assert_awaited_once_with(outlines)
    inner.set_sketch_construction.assert_awaited_once_with(["Line_1"], False)
    inner.add_arc.assert_awaited_once_with(0, 0, 1, 0, 0, 1, "cw")
