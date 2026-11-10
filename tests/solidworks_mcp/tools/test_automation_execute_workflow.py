"""``execute_workflow``: several tool calls in one request, run in order.

Each step goes through FastMCP's own ``call_tool``, so it gets the same input
validation, error boundary and settle pauses as a separate call.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import FastMCP
from pydantic import ValidationError

from solidworks_mcp.tools import register_tools
from solidworks_mcp.tools.automation import (
    MAX_WORKFLOW_STEPS,
    WorkflowInput,
    _step_arguments,
    _tool_result_payload,
)

_PLATE = [
    {"tool": "create_part", "arguments": {"name": "plate"}},
    {"tool": "create_sketch", "arguments": {"plane": "Top"}},
    {
        "tool": "add_rectangle",
        "arguments": {"x1": -50, "y1": -30, "x2": 50, "y2": 30},
    },
    {"tool": "exit_sketch"},
    {"tool": "create_extrusion", "arguments": {"input_data": {"depth": 10}}},
]


@pytest.fixture
async def server(mock_adapter, mock_config) -> FastMCP:
    """Every tool registered on the connected mock adapter."""
    mcp = FastMCP("workflow-tests")
    await register_tools(mcp, mock_adapter, mock_config)
    return mcp


async def _run(server: FastMCP, **input_data: Any) -> dict[str, Any]:
    reply = await server.call_tool("execute_workflow", {"input_data": input_data})
    return _tool_result_payload(reply)


@pytest.mark.asyncio
async def test_a_plate_builds_in_one_call(server) -> None:
    result = await _run(server, workflow_name="plate", steps=_PLATE)

    assert result["status"] == "success"
    assert result["completed"] == 5
    assert result["failed"] == []
    assert [step["tool"] for step in result["steps"]] == [
        step["tool"] for step in _PLATE
    ]
    assert all(step["status"] == "success" for step in result["steps"])
    assert result["steps"][4]["result"]["extrusion"]["depth"] == 10
    assert result["message"] == "Ran 5 steps of 'plate'"
    # Experimental until a live test runs it.
    assert result["warning"].startswith("Experimental:")


@pytest.mark.asyncio
async def test_the_first_failed_step_stops_the_run(server) -> None:
    result = await _run(
        server,
        steps=[
            {"tool": "create_part", "arguments": {"name": "p"}},
            {"tool": "create_extrusion", "arguments": {"depth": -1}},
            {"tool": "exit_sketch"},
        ],
    )

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_input"
    assert result["message"].startswith("Step 2 (create_extrusion) failed:")
    data = result["data"]
    assert data["completed"] == 1
    assert data["failed_step"] == 2
    assert [step["status"] for step in data["steps"]] == ["success", "error"]
    assert "depth" in data["steps"][1]["result"]["message"]
    assert result["hint"] == data["steps"][1]["result"]["hint"]


@pytest.mark.asyncio
async def test_continue_runs_every_step_and_reports_failures(server) -> None:
    result = await _run(
        server,
        error_handling="continue",
        steps=[
            {"tool": "create_extrusion", "arguments": {"depth": -1}},
            {"tool": "create_part", "arguments": {"name": "p"}},
        ],
    )

    assert result["status"] == "success"
    assert result["completed"] == 1
    assert result["failed"] == [1]
    assert result["message"] == "Ran 2 steps of 'workflow'; 1 failed"
    assert result["warning"].startswith("1 of 2 steps failed (steps [1])")


@pytest.mark.asyncio
async def test_a_tool_failure_inside_a_step_is_that_steps_error(server) -> None:
    """A tool's own error payload (not an exception) fails the step."""
    result = await _run(
        server,
        error_handling="continue",
        steps=[{"tool": "get_dimension", "arguments": {"name": ""}}],
    )

    assert result["failed"] == [1]
    step = result["steps"][0]
    assert step["status"] == "error"
    assert step["result"]["error_type"]


@pytest.mark.asyncio
async def test_unknown_tools_are_refused_before_anything_runs(server) -> None:
    result = await _run(
        server,
        steps=[
            {"tool": "create_part"},
            {"tool": "create_widget"},
            {"tool": "execute_workflow"},
        ],
    )

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_input"
    assert "steps[2]: no tool named `create_widget`" in result["message"]
    assert "steps[3]: execute_workflow can't be a step" in result["message"]
    assert "Nothing was run." in result["message"]


@pytest.mark.asyncio
async def test_parallel_execution_is_refused(server) -> None:
    result = await _run(server, parallel_execution=True, steps=[{"tool": "undo"}])

    assert result["status"] == "error"
    assert result["error_type"] == "invalid_input"
    assert "one at a time" in result["message"]


def test_skip_is_the_old_spelling_of_continue() -> None:
    parsed = WorkflowInput(steps=[{"tool": "undo"}], error_handling="skip")

    assert parsed.error_handling == "continue"


def test_the_step_count_is_capped() -> None:
    with pytest.raises(ValidationError):
        WorkflowInput(steps=[{"tool": "undo"}] * (MAX_WORKFLOW_STEPS + 1))
    with pytest.raises(ValidationError):
        WorkflowInput(steps=[])


def test_bare_fields_are_wrapped_only_for_input_data_tools() -> None:
    input_data_tool = SimpleNamespace(parameters={"properties": {"input_data": {}}})
    other_tool = SimpleNamespace(parameters={"properties": {"path": {}}})

    assert _step_arguments(input_data_tool, {"depth": 1}) == {
        "input_data": {"depth": 1}
    }
    assert _step_arguments(input_data_tool, {}) == {"input_data": {}}
    assert _step_arguments(input_data_tool, {"input_data": {"depth": 2}}) == {
        "input_data": {"depth": 2}
    }
    assert _step_arguments(other_tool, {"path": "x"}) == {"path": "x"}
    assert _step_arguments(SimpleNamespace(parameters=None), {"a": 1}) == {"a": 1}


def test_a_reply_without_structured_content_is_read_from_its_text() -> None:
    def reply(text: str) -> SimpleNamespace:
        return SimpleNamespace(
            structured_content=None, content=[SimpleNamespace(text=text)]
        )

    assert _tool_result_payload(reply('{"status": "error", "message": "x"}')) == {
        "status": "error",
        "message": "x",
    }
    assert _tool_result_payload(reply("[1, 2]")) == {
        "status": "success",
        "result": [1, 2],
    }
    assert _tool_result_payload(reply("plain words")) == {
        "status": "success",
        "result": "plain words",
    }


@pytest.mark.asyncio
async def test_an_exception_from_call_tool_becomes_the_steps_error() -> None:
    """Anything FastMCP raises other than bad arguments is classified."""
    from solidworks_mcp.tools.automation import WorkflowStep, _run_workflow_step

    class _Broken:
        async def call_tool(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("transport closed")

    record = await _run_workflow_step(
        _Broken(), 3, WorkflowStep(tool="undo"), SimpleNamespace(parameters={})
    )

    assert record["step"] == 3
    assert record["status"] == "error"
    assert record["result"]["message"] == "undo failed: transport closed"
    assert record["result"]["error_type"]


@pytest.mark.asyncio
async def test_a_pydantic_error_from_call_tool_is_invalid_input() -> None:
    from solidworks_mcp.tools.automation import WorkflowStep, _run_workflow_step

    class _Strict:
        async def call_tool(self, *_args: Any, **_kwargs: Any) -> Any:
            WorkflowInput.model_validate({"steps": "nope"})

    record = await _run_workflow_step(
        _Strict(), 1, WorkflowStep(tool="undo"), SimpleNamespace(parameters={})
    )

    assert record["result"]["error_type"] == "invalid_input"
    assert record["result"]["message"].startswith("Invalid input: steps")
