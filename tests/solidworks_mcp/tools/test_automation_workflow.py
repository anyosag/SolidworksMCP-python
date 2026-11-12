"""``execute_workflow``: tool steps in order, stopping at the first failure.

From the Cellvis dish-rack session: a batch tool that runs a list of steps,
stops on the first error, and can roll back to where it started. A later
session found that a step's ``document`` was ignored, that arguments wrapped
in ``input_data`` ran with defaults, that a step couldn't use an earlier
step's result, and that the replies were huge.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import ANY, AsyncMock

import pytest
from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.adapters.solidworks import limits
from solidworks_mcp.tools.automation import _warning_parts, register_automation_tools
from solidworks_mcp.tools.export import register_export_tools
from solidworks_mcp.tools.modeling import register_modeling_tools
from solidworks_mcp.tools.sketching import register_sketching_tools
from solidworks_mcp.tools.support_levels import SUPPORT_LEVELS

_BOX = [
    {"tool": "create_sketch", "arguments": {"plane": "Top"}},
    {"tool": "add_rectangle", "arguments": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}},
    {"tool": "exit_sketch"},
    {"tool": "create_extrusion", "arguments": {"depth": 5}},
]
#: The box, then step 4: a fillet whose reply has `fillet` (name, radius, edges).
_FILLETED = [
    *_BOX,
    {"tool": "add_fillet", "arguments": {"radius": 1, "edge_names": ["Edge<1>"]}},
]
_FAILING = {"tool": "select_edges", "arguments": {"feature": "Nope"}}
_VBA = {"tool": "generate_vba_code"}
_EXPERIMENTAL = SUPPORT_LEVELS["generate_vba_code"].warning()
_BASE = "DishRack_Base"


async def _server(adapter: MockSolidWorksAdapter, config: Any) -> Any:
    mcp = FastMCP("workflow")
    await register_sketching_tools(mcp, adapter, config)
    await register_modeling_tools(mcp, adapter, config)
    await register_export_tools(mcp, adapter, config)
    await register_automation_tools(mcp, adapter, config)
    return next(t.fn for t in await mcp.list_tools() if t.name == "execute_workflow")


@pytest.fixture
async def part(mock_config: Any) -> tuple[MockSolidWorksAdapter, Any]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    return adapter, await _server(adapter, mock_config)


@pytest.fixture
async def two_documents(mock_config: Any) -> tuple[MockSolidWorksAdapter, Any]:
    """A part, then an assembly, which is the active document."""
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part(name=_BASE)
    await adapter.create_assembly(name="DishRack")
    return adapter, await _server(adapter, mock_config)


async def test_a_box_in_one_call(part: Any) -> None:
    adapter, run = part

    result = await run({"workflow_name": "box", "steps": _BOX})

    assert result["status"] == "success", result
    assert result["message"] == "Workflow 'box' ran all 4 steps"
    assert result["completed"] == 4
    assert result["warnings"] == []
    assert [s["tool"] for s in result["steps"]] == [s["tool"] for s in _BOX]
    # The summary: the reply's scalars, `extrusion`'s scalars (its name) and
    # measured_change, but no lists.
    assert result["steps"][3] == {
        "index": 3,
        "tool": "create_extrusion",
        "status": "success",
        "message": "Created extrusion: Boss-Extrude1",
        "execution_time": ANY,
        "measured_change": ANY,
        "extrusion": ANY,
    }
    assert result["steps"][3]["extrusion"]["name"] == "Boss-Extrude1"
    assert not any(
        isinstance(v, (list, dict)) for v in result["steps"][3]["extrusion"].values()
    )
    assert any(f.type == "Extrusion" for f in adapter._features.values())


async def test_full_detail_gives_each_steps_whole_reply(part: Any) -> None:
    _adapter, run = part

    result = await run({"steps": [*_BOX, _VBA], "detail": "full"})

    assert result["status"] == "success", result
    assert result["steps"][3]["result"]["extrusion"]["depth"] == 5
    assert result["steps"][4]["result"]["warning"] == _EXPERIMENTAL
    assert result["warnings"] == [{"warning": _EXPERIMENTAL, "steps": [4]}]


async def test_a_summary_keeps_scalars_of_the_replys_data(part: Any) -> None:
    adapter, run = part
    steps = [*_FILLETED, {"tool": "delete_feature", "arguments": {"name": "Fillet1"}}]

    result = await run({"steps": steps})

    deleted = result["steps"][5]
    assert "result" not in deleted
    # `removed_features` and the other lists are left out.
    assert deleted["data"] == {
        "deleted": "Fillet1",
        "features_before": ANY,
        "features_after": ANY,
    }

    adapter.rename_feature = AsyncMock(  # type: ignore[method-assign]
        return_value=AdapterResult(
            status=AdapterResultStatus.SUCCESS, data={"aliases": ["A", "B"]}
        )
    )
    renamed = await run(
        {
            "steps": [
                {
                    "tool": "rename_feature",
                    "arguments": {"old_name": "a", "new_name": "b"},
                }
            ]
        }
    )

    assert "data" not in renamed["steps"][0]


async def test_a_warning_is_listed_once_with_its_steps(part: Any) -> None:
    _adapter, run = part

    result = await run({"steps": [_VBA, _BOX[0], _VBA]})

    assert result["warnings"] == [{"warning": _EXPERIMENTAL, "steps": [0, 2]}]
    assert not any("warning" in step for step in result["steps"])


async def test_a_one_time_notice_is_listed_apart_from_the_level(part: Any) -> None:
    adapter, run = part
    notices = iter(["Another MCP server is working on this document."])
    adapter.take_document_notice = lambda: next(notices, None)  # type: ignore[attr-defined]

    result = await run({"steps": [_VBA, _VBA]})

    assert result["warnings"] == [
        {"warning": _EXPERIMENTAL, "steps": [0, 1]},
        {"warning": "Another MCP server is working on this document.", "steps": [0]},
    ]


def test_a_warning_is_split_around_its_tools_level() -> None:
    joined = f"Own warning. {_EXPERIMENTAL} A notice."

    assert _warning_parts("generate_vba_code", joined) == [
        "Own warning.",
        _EXPERIMENTAL,
        "A notice.",
    ]
    assert _warning_parts("generate_vba_code", "Own warning.") == ["Own warning."]
    assert _warning_parts("create_extrusion", "Own warning.") == ["Own warning."]
    assert _warning_parts("create_extrusion", None) == []


async def test_it_stops_at_the_first_failure(part: Any) -> None:
    adapter, run = part

    result = await run({"steps": [*_BOX, _FAILING, *_BOX]})

    assert result["status"] == "error"
    assert result["error_type"] == "not_found"
    # The failed step's own hint comes through, not one for the workflow.
    assert result["hint"] == result["data"]["steps"][4]["result"]["hint"]
    assert result["message"].startswith(
        "Workflow 'workflow' stopped at step 5 of 9 (select_edges): "
    )
    assert result["data"]["failed_step"] == 4
    assert len(result["data"]["steps"]) == 5
    # Only the failed step carries its whole reply in a summary.
    assert "result" not in result["data"]["steps"][3]
    assert result["data"]["rolled_back"] is None
    assert result["data"]["warnings"] == []
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
        (_BOX, {"detail": "everything"}, "detail: Input should be 'summary' or 'full'"),
        ([{"tool": "add_line", "args": {}}], {}, "Extra inputs"),
        (
            [{"tool": "exit_sketch", "arguments": {"input_data": {"x": 1}}}],
            {},
            "exit_sketch takes no arguments",
        ),
        (
            [{"tool": "create_part", "arguments": {"name": "P", "document": "A"}}],
            {},
            "steps.0: create_part doesn't take document",
        ),
        (
            [{"tool": "exit_sketch", "arguments": {"document": "A"}, "document": "B"}],
            {},
            "steps.0: document is given more than once, as 'B' and 'A'",
        ),
        (
            [{"tool": "exit_sketch", "arguments": {"document": ["A"]}}],
            {},
            "steps.0: document must be the title, file name or path of an open "
            "document, not ['A']",
        ),
        (
            [_BOX[0], {"tool": "add_line", "arguments": {"x1": "$steps.zero.x"}}],
            {},
            "steps.1.arguments.x1: '$steps.zero.x' is not a reference",
        ),
        (
            [_BOX[0], {"tool": "add_line", "arguments": {"x1": "$steps.0"}}],
            {},
            "'$steps.0' is not a reference",
        ),
        (
            [
                {
                    "tool": "create_sketch",
                    "arguments": {"plane": "$steps.0.sketch.plane"},
                }
            ],
            {},
            "names step 0, which doesn't run before step 0",
        ),
        (
            [_BOX[0], {"tool": "exit_sketch", "document": "$steps.2.part.name"}],
            {},
            "steps.1.document: '$steps.2.part.name' names step 2",
        ),
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
    assert result["data"]["warnings"] == []
    assert not any(f.type == "Extrusion" for f in adapter._features.values())


@pytest.mark.parametrize(
    "where",
    ["arguments", "step", "both", "beside input_data", "inside input_data"],
)
async def test_a_step_runs_on_the_document_it_names(
    two_documents: Any, where: str, tmp_path: Any
) -> None:
    """The session's export_stl that ran on the active assembly instead."""
    adapter, run = two_documents
    stl = str(tmp_path / "base.stl")
    step = {
        "arguments": {
            "tool": "export_stl",
            "arguments": {"file_path": stl, "document": _BASE},
        },
        "step": {
            "tool": "export_stl",
            "arguments": {"file_path": stl},
            "document": _BASE,
        },
        "both": {
            "tool": "export_stl",
            "arguments": {"file_path": stl, "document": _BASE},
            "document": _BASE,
        },
        "beside input_data": {
            "tool": "export_stl",
            "arguments": {"input_data": {"file_path": stl}, "document": _BASE},
        },
        "inside input_data": {
            "tool": "export_stl",
            "arguments": {"input_data": {"file_path": stl, "document": _BASE}},
        },
    }[where]

    result = await run({"steps": [step]})

    assert result["status"] == "success", result
    assert adapter._current_model.name == _BASE


async def test_a_step_without_input_takes_a_document_too(two_documents: Any) -> None:
    adapter, run = two_documents
    steps = [
        {"tool": "create_sketch", "arguments": {"plane": "Top"}, "document": _BASE},
        {"tool": "exit_sketch", "document": _BASE},
    ]

    result = await run({"steps": steps})

    assert result["status"] == "success", result
    assert adapter._current_model.name == _BASE


async def test_a_document_that_isnt_open_fails_its_step(two_documents: Any) -> None:
    _adapter, run = two_documents
    steps = [
        {"tool": "create_sketch", "arguments": {"plane": "Top", "document": "Nope"}}
    ]

    result = await run({"steps": steps})

    assert result["data"]["failed_step"] == 0
    assert "could not make 'Nope' the active document" in result["message"]


async def test_arguments_wrapped_in_input_data_are_unwrapped(part: Any) -> None:
    """The session's create_reference_plane that ran with its defaults."""
    _adapter, run = part
    plane = {"input_data": {"reference": "Top Plane", "offset": 10}}

    result = await run(
        {
            "steps": [{"tool": "create_reference_plane", "arguments": plane}],
            "detail": "full",
        }
    )

    assert result["status"] == "success", result
    assert result["steps"][0]["result"]["plane"]["offset"] == 10


async def test_a_step_uses_a_value_from_an_earlier_reply(part: Any) -> None:
    """The session's rename_feature that hard-coded "Fillet1" and missed."""
    _adapter, run = part
    rename = {
        "tool": "rename_feature",
        # A string with $steps in the middle of it is not a reference.
        "arguments": {"old_name": "$steps.4.fillet.name", "new_name": "Edge $steps.4"},
    }

    # The summary leaves `fillet` out; the reference still finds it.
    result = await run({"steps": [*_FILLETED, rename]})

    assert result["status"] == "success", result
    assert result["steps"][5]["data"] == {
        "renamed": True,
        "old_name": "Fillet1",
        "new_name": "Edge $steps.4",
    }


async def test_a_reference_reaches_into_lists_both_ways(part: Any) -> None:
    _adapter, run = part
    again = {
        "tool": "add_fillet",
        "arguments": {"radius": 2, "edge_names": ["$steps.4.fillet.edges.0"]},
    }

    result = await run({"steps": [*_FILLETED, again], "detail": "full"})

    assert result["steps"][5]["result"]["fillet"]["edges"] == ["Edge<1>"]


async def test_a_document_can_come_from_an_earlier_reply(part: Any) -> None:
    adapter, run = part
    steps = [
        {"tool": "create_part", "arguments": {"name": "Lid"}},
        {"tool": "create_part", "arguments": {"name": "Other"}},
        {"tool": "create_sketch", "arguments": {"plane": "Top"}},
        {"tool": "exit_sketch", "document": "$steps.0.part.name"},
    ]

    result = await run({"steps": steps})

    assert result["status"] == "success", result
    assert adapter._current_model.name == "Lid"


async def test_a_document_reference_to_a_non_name_fails_its_step(part: Any) -> None:
    _adapter, run = part
    steps = [
        {"tool": "create_part", "arguments": {"name": "Lid"}},
        {"tool": "exit_sketch", "document": "$steps.0.part"},
    ]

    result = await run({"steps": steps})

    assert result["error_type"] == "invalid_input"
    assert result["data"]["failed_step"] == 1
    assert "steps.1.document: '$steps.0.part' is {" in result["message"]
    assert "not the name of a document" in result["message"]


@pytest.mark.parametrize(
    ("reference", "fragment"),
    [
        (
            "$steps.4.nope",
            "names 'nope', which $steps.4 doesn't have; its keys are: status, "
            "message, fillet, execution_time",
        ),
        (
            "$steps.4.fillet.nope",
            "names 'nope', which $steps.4.fillet doesn't have; its keys are: "
            "name, radius, edges",
        ),
        (
            "$steps.4.fillet.edges.7",
            "names '7', which $steps.4.fillet.edges doesn't have; it is a list "
            "of 1 items, numbered from 0",
        ),
        (
            "$steps.4.fillet.name.x",
            "names 'x', which $steps.4.fillet.name doesn't have; it is 'Fillet1', "
            "not an object or a list",
        ),
    ],
)
async def test_a_reference_to_nothing_fails_its_step(
    part: Any, reference: str, fragment: str
) -> None:
    _adapter, run = part
    rename = {
        "tool": "rename_feature",
        "arguments": {"old_name": reference, "new_name": "Round"},
    }

    result = await run({"steps": [*_FILLETED, rename]})

    assert result["error_type"] == "invalid_input"
    assert result["data"]["failed_step"] == 5
    assert result["message"].startswith(
        "Workflow 'workflow' stopped at step 6 of 6 (rename_feature): Invalid "
        f"input: steps.5.arguments.old_name: {reference!r} {fragment}"
    )
    assert "detail 'full'" in result["hint"]
    assert result["data"]["steps"][5]["result"]["error_type"] == "invalid_input"
