"""The circuit breaker forwards show/hide, delete's sketch flag and pattern reversal."""

from __future__ import annotations

from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_the_breaker_passes_the_new_arguments_through() -> None:
    inner = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    for name in ("set_visibility", "delete_feature", "pattern_circular"):
        setattr(inner, name, AsyncMock(return_value=ok))
    breaker = CircuitBreakerAdapter(adapter=inner)

    assert (await breaker.set_visibility(["Plane1"], ["axes"], True)) is ok
    assert (await breaker.delete_feature("Cut1", True)) is ok
    assert (
        await breaker.pattern_circular(["Cut1"], "Axis1", 3, 60.0, False, True)
    ) is ok

    inner.set_visibility.assert_awaited_once_with(["Plane1"], ["axes"], True)
    inner.delete_feature.assert_awaited_once_with("Cut1", True)
    inner.pattern_circular.assert_awaited_once_with(
        ["Cut1"], "Axis1", 3, 60.0, False, True
    )
