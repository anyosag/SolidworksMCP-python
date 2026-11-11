"""The connection pool forwards the outline, construction and arc-direction calls."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.connection_pool import ConnectionPoolAdapter


async def test_the_pool_passes_every_argument_through() -> None:
    ok = AdapterResult(status=AdapterResultStatus.SUCCESS, data={"done": True})
    stub = SimpleNamespace(
        add_sketch_outlines=AsyncMock(return_value=ok),
        set_sketch_construction=AsyncMock(return_value=ok),
        add_arc=AsyncMock(return_value=ok),
    )
    pool = ConnectionPoolAdapter(adapter_factory=lambda: stub, pool_size=1)
    names: list[str] = []

    async def passthrough(operation_name: str, operation: object) -> object:
        names.append(operation_name)
        return await operation(stub)  # type: ignore[operator]

    pool._execute_with_pool = AsyncMock(side_effect=passthrough)  # type: ignore[method-assign]
    outlines = [{"segments": [], "construction": True}]

    assert (await pool.add_sketch_outlines(outlines)) is ok
    assert (await pool.set_sketch_construction(["Arc_2"])) is ok
    assert (await pool.add_arc(0, 0, 1, 0, 0, 1, "cw")) is ok

    assert names == ["add_sketch_outlines", "set_sketch_construction", "add_arc"]
    stub.add_sketch_outlines.assert_awaited_once_with(outlines)
    stub.set_sketch_construction.assert_awaited_once_with(["Arc_2"], True)
    stub.add_arc.assert_awaited_once_with(0, 0, 1, 0, 0, 1, "cw")
