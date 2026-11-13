"""The connection pool forwards ``check_printability``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter


async def test_the_pool_passes_every_argument() -> None:
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    stub = SimpleNamespace(check_printability=AsyncMock(return_value=ok))
    pool = ConnectionPoolAdapter(adapter_factory=lambda: stub, pool_size=1)

    async def passthrough(_name: str, operation: object) -> object:
        return await operation(stub)  # type: ignore[operator]

    pool._execute_with_pool = AsyncMock(side_effect=passthrough)  # type: ignore[method-assign]

    assert (await pool.check_printability([0, 1, 0], 30.0, 2.0)) is ok
    stub.check_printability.assert_awaited_once_with([0, 1, 0], 30.0, 2.0)
