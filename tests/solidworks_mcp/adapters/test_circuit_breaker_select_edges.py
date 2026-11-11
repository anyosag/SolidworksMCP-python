"""The circuit breaker forwards ``select_edges`` and doesn't count "no match"."""

from __future__ import annotations

from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter, CircuitState
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_no_match_never_opens_the_breaker() -> None:
    inner = MockSolidWorksAdapter({})
    miss = AdapterResult(
        status=AdapterResultStatus.ERROR, error="No matching edges found"
    )
    inner.select_edges = AsyncMock(return_value=miss)  # type: ignore[method-assign]
    breaker = CircuitBreakerAdapter(adapter=inner, failure_threshold=2)

    for _ in range(3):
        assert (await breaker.select_edges({"side": "top"}, True)) is miss

    inner.select_edges.assert_awaited_with({"side": "top"}, True)
    assert breaker._get_bucket("select_edges").state == CircuitState.CLOSED
