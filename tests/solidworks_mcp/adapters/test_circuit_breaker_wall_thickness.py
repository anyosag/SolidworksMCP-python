"""The circuit breaker forwards ``check_wall_thickness``."""

from __future__ import annotations

from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter

_BOXES = [[0.0, 0.0, 0.0, 1.0, 1.0, 1.0]]


async def test_the_breaker_passes_every_argument() -> None:
    inner = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    inner.check_wall_thickness = AsyncMock(return_value=ok)  # type: ignore[method-assign]

    assert (
        await CircuitBreakerAdapter(adapter=inner).check_wall_thickness(1.2, 99, _BOXES)
    ) is ok
    inner.check_wall_thickness.assert_awaited_once_with(1.2, 99, _BOXES)
