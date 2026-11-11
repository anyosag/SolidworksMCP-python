"""The circuit breaker forwards STL exports with mesh settings."""

from __future__ import annotations

from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_the_breaker_passes_the_settings_through() -> None:
    inner = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    inner.export_stl_with_settings = AsyncMock(return_value=ok)  # type: ignore[method-assign]
    breaker = CircuitBreakerAdapter(adapter=inner)

    assert (await breaker.export_stl_with_settings("o.stl", {"units": "mm"})) is ok
    inner.export_stl_with_settings.assert_awaited_once_with("o.stl", {"units": "mm"})
