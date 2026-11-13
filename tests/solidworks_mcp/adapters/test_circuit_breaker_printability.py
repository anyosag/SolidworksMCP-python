"""The circuit breaker forwards ``check_printability``."""

from __future__ import annotations

from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_the_breaker_passes_every_argument() -> None:
    inner = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    inner.check_printability = AsyncMock(return_value=ok)  # type: ignore[method-assign]

    assert (
        await CircuitBreakerAdapter(adapter=inner).check_printability("-y", 40.0, 8.0)
    ) is ok
    inner.check_printability.assert_awaited_once_with("-y", 40.0, 8.0)
