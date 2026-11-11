"""The connection pool forwards ``select_edges``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter


async def test_the_pool_passes_the_query_and_append_through() -> None:
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={"selected_edges": 4})
    stub = SimpleNamespace(select_edges=AsyncMock(return_value=ok))
    pool = ConnectionPoolAdapter(adapter_factory=lambda: stub, pool_size=1)

    async def passthrough(_name: str, operation: object) -> object:
        return await operation(stub)  # type: ignore[operator]

    pool._execute_with_pool = AsyncMock(side_effect=passthrough)  # type: ignore[method-assign]

    assert (await pool.select_edges({"parallel_to": "y"})) is ok
    stub.select_edges.assert_awaited_once_with({"parallel_to": "y"}, False)
