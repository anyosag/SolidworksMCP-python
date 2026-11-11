"""The connection pool forwards show/hide, delete's sketch flag and pattern reversal."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter


async def test_the_pool_passes_the_new_arguments_through() -> None:
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    stub = SimpleNamespace(
        set_visibility=AsyncMock(return_value=ok),
        delete_feature=AsyncMock(return_value=ok),
        pattern_circular=AsyncMock(return_value=ok),
    )
    pool = ConnectionPoolAdapter(adapter_factory=lambda: stub, pool_size=1)

    async def passthrough(_name: str, operation: object) -> object:
        return await operation(stub)  # type: ignore[operator]

    pool._execute_with_pool = AsyncMock(side_effect=passthrough)  # type: ignore[method-assign]

    assert (await pool.set_visibility(None, ["planes"], False)) is ok
    assert (await pool.delete_feature("Cut1", True)) is ok
    assert (await pool.pattern_circular(["Cut1"], "Axis1", 3, 60.0, False, True)) is ok

    stub.set_visibility.assert_awaited_once_with(None, ["planes"], False)
    stub.delete_feature.assert_awaited_once_with("Cut1", True)
    stub.pattern_circular.assert_awaited_once_with(
        ["Cut1"], "Axis1", 3, 60.0, False, True
    )
