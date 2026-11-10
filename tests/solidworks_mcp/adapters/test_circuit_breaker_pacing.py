"""The circuit breaker paces COM work and forwards the running check.

Some adapter methods make COM calls before reaching
``_handle_com_operation`` (re-reading ``ActiveDoc``, flagging). The breaker
asks the adapter to wait out the settle gap as each method starts, so those
calls keep the gap too.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter


class _PacedAdapter:
    """An adapter that records the order of pacing and work."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def pace_before_com(self) -> None:
        self.events.append("pace")

    def is_application_running(self) -> bool:
        return False

    async def get_model_info(self) -> AdapterResult[dict]:
        self.events.append("work")
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data={})


@pytest.mark.asyncio
async def test_each_method_waits_out_the_gap_before_its_work() -> None:
    inner = _PacedAdapter()
    breaker = CircuitBreakerAdapter(adapter=inner)

    await breaker.get_model_info()

    assert inner.events == ["pace", "work"]


@pytest.mark.asyncio
async def test_a_test_double_without_pacing_is_left_alone() -> None:
    inner = Mock()
    inner.get_model_info = AsyncMock(
        return_value=AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    )
    breaker = CircuitBreakerAdapter(adapter=inner)

    result = await breaker.get_model_info()

    assert result.is_success
    inner.pace_before_com.assert_not_called()


def test_the_running_check_is_forwarded() -> None:
    assert (
        CircuitBreakerAdapter(adapter=_PacedAdapter()).is_application_running() is False
    )


def test_an_adapter_without_a_running_check_counts_as_running() -> None:
    assert CircuitBreakerAdapter(adapter=Mock()).is_application_running() is True
