"""The connection pool forwards ``use_document`` and the shared-document notice."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter


async def test_the_pool_forwards_document_choice() -> None:
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    quiet = SimpleNamespace(
        use_document=AsyncMock(return_value=ok), take_document_notice=lambda: None
    )
    noisy = SimpleNamespace(take_document_notice=lambda: "shared")
    pool = ConnectionPoolAdapter(adapter_factory=lambda: quiet, pool_size=1)

    async def passthrough(_name: str, operation: object) -> object:
        return await operation(quiet)  # type: ignore[operator]

    pool._execute_with_pool = AsyncMock(side_effect=passthrough)  # type: ignore[method-assign]

    assert (await pool.use_document("Part7")) is ok
    quiet.use_document.assert_awaited_once_with("Part7")
    assert pool.take_document_notice() is None
    pool.pool = [quiet, noisy]  # type: ignore[list-item]
    assert pool.take_document_notice() == "shared"
