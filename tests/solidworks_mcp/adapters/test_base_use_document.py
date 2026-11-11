"""The base adapter's defaults for ``use_document`` and ``take_document_notice``."""

from __future__ import annotations

from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_by_default_a_document_is_activated_every_time() -> None:
    adapter = MockSolidWorksAdapter({})
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={"activated": "P"})
    adapter.activate_document = AsyncMock(return_value=ok)  # type: ignore[method-assign]

    assert (await adapter.use_document("P")) is ok
    assert (await adapter.use_document("P")) is ok

    assert adapter.activate_document.await_count == 2
    assert adapter.take_document_notice() is None
