"""The connection pool forwards ``measure_clearance``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter


async def test_the_pool_passes_both_components() -> None:
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    stub = SimpleNamespace(measure_clearance=AsyncMock(return_value=ok))
    pool = ConnectionPoolAdapter(adapter_factory=lambda: stub, pool_size=1)

    async def passthrough(_name: str, operation: object) -> object:
        return await operation(stub)  # type: ignore[operator]

    pool._execute_with_pool = AsyncMock(side_effect=passthrough)  # type: ignore[method-assign]

    assert (await pool.measure_clearance("tongue-1", "slot-1")) is ok
    stub.measure_clearance.assert_awaited_once_with("tongue-1", "slot-1")
    assert pool._execute_with_pool.await_args.args[0] == "measure_clearance"
