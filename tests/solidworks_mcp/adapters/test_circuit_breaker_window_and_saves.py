"""The circuit breaker forwards the window tool and the save confirmation flag."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter, CircuitState


def _ok(data: object = None) -> AdapterResult[object]:
    return AdapterResult(status=AdapterResultStatus.SUCCESS, data=data)


@pytest.fixture
def inner() -> AsyncMock:
    adapter = AsyncMock()
    adapter.set_window_state = AsyncMock(
        return_value=_ok({"window_state": "minimized"})
    )
    adapter.save_file = AsyncMock(return_value=_ok())
    adapter.close_model = AsyncMock(return_value=_ok())
    return adapter


async def test_set_window_state_bypasses_the_breaker(inner: AsyncMock) -> None:
    breaker = CircuitBreakerAdapter(adapter=inner, failure_threshold=1)
    breaker._get_bucket("set_window_state").state = CircuitState.OPEN

    result = await breaker.set_window_state("minimize")

    assert result.data == {"window_state": "minimized"}
    inner.set_window_state.assert_awaited_once_with("minimize")


async def test_save_and_close_forward_the_confirmation(inner: AsyncMock) -> None:
    breaker = CircuitBreakerAdapter(adapter=inner)

    assert (await breaker.save_file("C:/a.SLDASM", True)).is_success
    assert (await breaker.close_model(True, True)).is_success

    inner.save_file.assert_awaited_once_with("C:/a.SLDASM", True)
    inner.close_model.assert_awaited_once_with(True, True)


def test_set_window_state_is_not_inherited_from_the_base_stub() -> None:
    from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter

    for cls in (CircuitBreakerAdapter, ConnectionPoolAdapter):
        assert "set_window_state" in vars(cls)
