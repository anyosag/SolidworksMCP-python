"""The connection pool forwards ``check_wall_thickness``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter

_BOXES = [[0.0, 0.0, 0.0, 1.0, 1.0, 1.0]]


async def test_the_pool_passes_every_argument() -> None:
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    stub = SimpleNamespace(check_wall_thickness=AsyncMock(return_value=ok))
    pool = ConnectionPoolAdapter(adapter_factory=lambda: stub, pool_size=1)

    async def passthrough(_name: str, operation: object) -> object:
        return await operation(stub)  # type: ignore[operator]

    pool._execute_with_pool = AsyncMock(side_effect=passthrough)  # type: ignore[method-assign]

    assert (await pool.check_wall_thickness(0.6, 300, _BOXES)) is ok
    stub.check_wall_thickness.assert_awaited_once_with(0.6, 300, _BOXES)
