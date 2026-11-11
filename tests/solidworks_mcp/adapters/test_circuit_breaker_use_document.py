"""The circuit breaker forwards ``use_document`` and the shared-document notice."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_the_breaker_forwards_document_choice() -> None:
    inner = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    inner.use_document = AsyncMock(return_value=ok)  # type: ignore[method-assign]
    inner.take_document_notice = Mock(return_value="shared")  # type: ignore[method-assign]
    breaker = CircuitBreakerAdapter(adapter=inner)

    assert (await breaker.use_document("Part7")) is ok
    assert breaker.take_document_notice() == "shared"

    inner.use_document.assert_awaited_once_with("Part7")
