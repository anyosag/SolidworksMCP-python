"""``reset_circuit_breaker`` (spec: adapters/circuit-breaker, the reset requirement)."""

from __future__ import annotations

from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.circuit_breaker import CircuitBreakerAdapter, CircuitState
from solidworks_mcp.tools.server_admin import (
    ResetCircuitBreakerInput,
    SetSolidWorksWindowInput,
    register_server_admin_tools,
)


async def _reset_tool(mcp_server: Any, adapter: Any) -> Any:
    await register_server_admin_tools(mcp_server, adapter, {})
    return next(
        t.fn for t in await mcp_server.list_tools() if t.name == "reset_circuit_breaker"
    )


def _breaker_with_open(*operations: str) -> CircuitBreakerAdapter:
    breaker = CircuitBreakerAdapter(failure_threshold=1)
    for name in operations:
        breaker._get_bucket(name).state = CircuitState.OPEN
    return breaker


@pytest.mark.asyncio
async def test_registers_two_tools(mcp_server, mock_adapter) -> None:
    assert await register_server_admin_tools(mcp_server, mock_adapter, {}) == 2


async def _window_tool(mcp_server: Any, adapter: Any) -> Any:
    await register_server_admin_tools(mcp_server, adapter, {})
    return next(
        t.fn for t in await mcp_server.list_tools() if t.name == "set_solidworks_window"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected"), [("minimize", "minimized"), ("restore", "normal")]
)
async def test_set_solidworks_window(
    mcp_server, mock_adapter, state: str, expected: str
) -> None:
    tool = await _window_tool(mcp_server, mock_adapter)

    result = await tool(SetSolidWorksWindowInput(state=state))

    assert result == {
        "status": "success",
        "message": f"SolidWorks window is {expected}",
        "data": {"window_state": expected},
    }


@pytest.mark.asyncio
async def test_set_solidworks_window_rejects_other_states(
    mcp_server, mock_adapter
) -> None:
    tool = await _window_tool(mcp_server, mock_adapter)

    result = await tool({"state": "maximize"})

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_input"


@pytest.mark.asyncio
async def test_set_solidworks_window_without_a_window(mcp_server) -> None:
    class _NoWindow:
        async def set_window_state(self, state: str) -> AdapterResult[Any]:
            return AdapterResult(
                status=AdapterResultStatus.ERROR,
                error="The SolidWorks window is not available (not connected)",
            )

    tool = await _window_tool(mcp_server, _NoWindow())

    result = await tool(SetSolidWorksWindowInput(state="minimize"))

    assert result["status"] == "error"
    assert "Failed to change the SolidWorks window" in result["message"]


@pytest.mark.asyncio
async def test_without_a_breaker_nothing_was_paused(mcp_server, mock_adapter) -> None:
    tool = await _reset_tool(mcp_server, mock_adapter)

    result = await tool()

    assert result["status"] == "success"
    assert result["data"] == {"reset": []}
    assert result["message"] == "No operation was paused"


@pytest.mark.asyncio
async def test_resets_every_open_operation(mcp_server) -> None:
    breaker = _breaker_with_open("create_extrusion", "add_mate")
    tool = await _reset_tool(mcp_server, breaker)

    result = await tool()

    assert result["data"] == {"reset": ["add_mate", "create_extrusion"]}
    assert result["message"] == "Reset add_mate, create_extrusion"
    assert breaker._get_bucket("add_mate").state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_resets_only_the_named_operation(mcp_server) -> None:
    breaker = _breaker_with_open("create_extrusion", "add_mate")
    tool = await _reset_tool(mcp_server, breaker)

    result = await tool(ResetCircuitBreakerInput(operation="create_extrusion"))

    assert result["data"] == {"reset": ["create_extrusion"]}
    assert breaker._get_bucket("add_mate").state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_a_failed_reset_is_an_error(mcp_server) -> None:
    class _Broken:
        async def reset_circuit_breakers(
            self, operation: str | None
        ) -> AdapterResult[Any]:
            return AdapterResult(status=AdapterResultStatus.ERROR, error="pool closed")

    tool = await _reset_tool(mcp_server, _Broken())

    result = await tool()

    assert result["status"] == "error"
    assert "Failed to reset the circuit breaker" in result["message"]
