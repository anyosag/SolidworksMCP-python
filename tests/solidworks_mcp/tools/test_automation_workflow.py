"""``execute_workflow``: tool steps in order, stopping at the first failure.

From the Cellvis dish-rack session: a batch tool that runs a list of steps,
stops on the first error, and can roll back to where it started.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.adapters.solidworks import limits
from solidworks_mcp.tools.automation import register_automation_tools
from solidworks_mcp.tools.modeling import register_modeling_tools
from solidworks_mcp.tools.sketching import register_sketching_tools

_BOX = [
    {"tool": "create_sketch", "arguments": {"plane": "Top"}},
    {"tool": "add_rectangle", "arguments": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}},
    {"tool": "exit_sketch"},
    {"tool": "create_extrusion", "arguments": {"depth": 5}},
]
_FAILING = {"tool": "select_edges", "arguments": {"feature": "Nope"}}


async def _server(adapter: MockSolidWorksAdapter, config: Any) -> Any:
    mcp = FastMCP("workflow")
    await register_sketching_tools(mcp, adapter, config)
    await register_modeling_tools(mcp, adapter, config)
    await register_automation_tools(mcp, adapter, config)
    return next(t.fn for t in await mcp.list_tools() if t.name == "execute_workflow")


@pytest.fixture
async def part(mock_config: Any) -> tuple[MockSolidWorksAdapter, Any]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    return adapter, await _server(adapter, mock_config)


async def test_a_box_in_one_call(part: Any) -> None:
    adapter, run = part

    result = await run({"workflow_name": "box", "steps": _BOX})

    assert result["status"] == "success", result
    assert result["message"] == "Workflow 'box' ran all 4 steps"
    assert result["completed"] == 4
    assert [s["tool"] for s in result["steps"]] == [s["tool"] for s in _BOX]
    assert result["steps"][3]["result"]["extrusion"]["depth"] == 5
    assert any(f.type == "Extrusion" for f in adapter._features.values())


async def test_it_stops_at_the_first_failure(part: Any) -> None:
    adapter, run = part

    result = await run({"steps": [*_BOX, _FAILING, *_BOX]})

    assert result["status"] == "error"
    assert result["error_type"] == "not_found"
    assert result["message"].startswith(
        "Workflow 'workflow' stopped at step 5 of 9 (select_edges): "
    )
    assert result["data"]["failed_step"] == 4
    assert len(result["data"]["steps"]) == 5
    assert result["data"]["rolled_back"] is None
    assert sum(f.type == "Extrusion" for f in adapter._features.values()) == 1


async def test_rollback_deletes_what_the_steps_built(part: Any) -> None:
    adapter, run = part

    result = await run({"steps": [*_BOX, _FAILING], "rollback_on_error": True})

    rolled = result["data"]["rolled_back"]
    assert rolled["done"] is True
    assert rolled["deleted"][0].startswith("Boss-Extrude")
    assert not adapter._features


async def test_a_rollback_that_cannot_delete_says_what_is_left(part: Any) -> None:
    adapter, run = part
    adapter.delete_feature = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(status=AdapterResultStatus.ERROR, error="locked")
    )

    result = await run({"steps": [*_BOX, _FAILING], "rollback_on_error": True})

    rolled = result["data"]["rolled_back"]
    assert rolled["done"] is False
    assert "would not delete" in rolled["reason"] and "locked" in rolled["reason"]
    assert rolled["left"]


async def test_no_rollback_without_a_document_at_the_start(mock_config: Any) -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    run = await _server(adapter, mock_config)

    result = await run({"steps": [*_BOX, _FAILING], "rollback_on_error": True})

    assert (
        "no document was open at the start" in result["data"]["rolled_back"]["reason"]
    )


async def test_no_rollback_after_the_document_changed(part: Any) -> None:
    _adapter, run = part
    steps = [{"tool": "create_part", "arguments": {"name": "Another"}}, *_BOX, _FAILING]

    result = await run({"steps": steps, "rollback_on_error": True})

    assert "is no longer" in result["data"]["rolled_back"]["reason"]


async def test_no_rollback_when_the_tree_was_unreadable(part: Any) -> None:
    adapter, run = part
    adapter.list_features = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(status=AdapterResultStatus.ERROR, error="busy")
    )

    result = await run({"steps": [_FAILING], "rollback_on_error": True})

    assert "couldn't be read at the start" in result["data"]["rolled_back"]["reason"]


async def test_a_document_without_a_title_counts_as_none(part: Any) -> None:
    adapter, run = part
    adapter.get_model_info = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    )

    result = await run({"steps": [_FAILING], "rollback_on_error": True})

    assert "no document was open" in result["data"]["rolled_back"]["reason"]


@pytest.mark.parametrize(
    ("steps", "extra", "fragment"),
    [
        ([{"tool": "execute_workflow"}], {}, "can't run execute_workflow"),
        ([{"tool": "make_coffee"}], {}, "no tool named 'make_coffee'"),
        ([{"tool": "exit_sketch", "arguments": {"x": 1}}], {}, "takes no arguments"),
        (
            [{"tool": "rename_feature", "arguments": {}}],
            {"rollback_on_error": True},
            "rollback_on_error can't be used with rename_feature",
        ),
        ([], {}, "steps"),
        (_BOX, {"parallel_execution": True}, "`parallel_execution` is no longer"),
        (_BOX, {"error_handling": "skip"}, "`error_handling` is no longer"),
        ([{"tool": "add_line", "args": {}}], {}, "Extra inputs"),
    ],
)
async def test_bad_workflows_run_nothing(
    part: Any, steps: list[dict[str, Any]], extra: dict[str, Any], fragment: str
) -> None:
    adapter, run = part

    result = await run({"steps": steps, **extra})

    assert result["error_type"] == "invalid_input", result
    assert fragment in result["message"]
    assert not adapter._features


async def test_a_planned_tool_is_refused(mock_config: Any) -> None:
    """A step naming a tool that can't run yet is refused before any step runs."""
    from solidworks_mcp.tools.export import register_export_tools

    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    mcp = FastMCP("workflow-planned")
    await register_export_tools(mcp, adapter, mock_config)
    await register_automation_tools(mcp, adapter, mock_config)
    run = next(t.fn for t in await mcp.list_tools() if t.name == "execute_workflow")

    result = await run({"steps": [{"tool": "batch_export", "arguments": {}}]})

    assert "batch_export is not available yet" in result["message"]


async def test_progress_is_reported_before_each_step_and_at_the_end(part: Any) -> None:
    _adapter, run = part
    ctx = AsyncMock()

    result = await run({"steps": _BOX}, ctx)

    assert result["status"] == "success"
    calls = [c.kwargs for c in ctx.report_progress.await_args_list]
    assert [(c["progress"], c["total"]) for c in calls] == [
        (0, 4),
        (1, 4),
        (2, 4),
        (3, 4),
        (4, 4),
    ]
    assert calls[1]["message"] == "Step 2 of 4: add_rectangle"
    assert calls[-1]["message"] == "All 4 steps done"


async def test_a_workflow_stops_between_steps_when_the_client_has_gone(
    part: Any,
) -> None:
    adapter, run = part
    limits.mark_client_gone("test")

    result = await run({"steps": _BOX})

    assert result["status"] == "error"
    assert result["error_type"] == "operation_stopped"
    assert result["message"].startswith(
        "Workflow 'workflow' stopped before step 1 of 4 (create_sketch)"
    )
    assert result["data"]["completed"] == 0
    assert not any(f.type == "Extrusion" for f in adapter._features.values())
