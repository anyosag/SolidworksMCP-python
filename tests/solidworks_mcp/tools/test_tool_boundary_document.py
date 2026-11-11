"""The boundary's ``document`` argument, and the shared-document warning.

From the Cellvis dish rack: two clients on one SolidWorks had to call
``activate_document`` before every call to be sure of their target. Every
document tool now takes ``document``; the boundary activates it first.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import FastMCP
from pydantic import BaseModel

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.modeling import register_modeling_tools
from solidworks_mcp.tools.tool_boundary import (
    ToolRegistrar,
    takes_input,
    tool_boundary,
)


async def _two_parts(config: Any) -> tuple[MockSolidWorksAdapter, FastMCP, list[str]]:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    await adapter.create_part()
    titles = [doc["title"] for doc in (await adapter.list_open_documents()).data]
    mcp = FastMCP("documents")
    await register_modeling_tools(mcp, adapter, config)
    return adapter, mcp, titles


async def test_document_tools_advertise_document_and_choosers_do_not(
    mock_config: Any,
) -> None:
    _adapter, mcp, _titles = await _two_parts(mock_config)
    tools = {t.name: t for t in await mcp.list_tools()}

    document = tools["rebuild_model"].parameters["properties"]["document"]

    assert document["description"].startswith("The open document to work on")
    assert "document" not in tools["open_model"].parameters.get("properties", {})
    assert "document" not in tools["rebuild_model"].parameters.get("required", [])


async def test_a_call_with_document_works_on_that_document(mock_config: Any) -> None:
    adapter, mcp, titles = await _two_parts(mock_config)
    assert adapter._current_model.name == titles[1]

    reply = await mcp.call_tool("rebuild_model", {"document": titles[0]})

    assert reply.structured_content["status"] == "success"
    assert adapter._current_model.name == titles[0]


async def test_a_document_that_is_not_open_runs_nothing(mock_config: Any) -> None:
    adapter, mcp, _titles = await _two_parts(mock_config)
    adapter.rebuild_model = AsyncMock()  # type: ignore[method-assign]

    reply = (
        await mcp.call_tool("rebuild_model", {"document": "Nope"})
    ).structured_content

    assert reply["status"] == "error"
    assert reply["error_type"] == "not_found"
    assert reply["message"].startswith(
        "rebuild_model was not run: could not make 'Nope' the active document: "
        "No open document matches 'Nope'"
    )
    adapter.rebuild_model.assert_not_awaited()


async def test_invalid_input_switches_no_document(mock_config: Any) -> None:
    adapter, mcp, titles = await _two_parts(mock_config)
    tools = {t.name: t.fn for t in await mcp.list_tools()}

    reply = await tools["rename_feature"]({"new_name": 5}, document=titles[0])

    assert reply["error_type"] == "invalid_input"
    assert adapter._current_model.name == titles[1]


class _In(BaseModel):
    value: int = 1


async def _tool(input_data: _In) -> dict[str, Any]:
    return {"status": "success", "message": "ok", "warning": "own."}


_tool.__module__ = "solidworks_mcp.tools.modeling"
_tool.__name__ = "rename_feature"


def _adapter(notice: Any) -> Any:
    adapter = Mock()
    adapter.take_document_notice = Mock(return_value=notice)
    adapter.use_document = AsyncMock(
        return_value=AdapterResult(status=AdapterResultStatus.SUCCESS, data={})
    )
    return adapter


async def test_the_shared_document_warning_follows_the_others() -> None:
    wrapped = tool_boundary(_tool, warning="Beta.", adapter=_adapter("Shared."))

    result = await wrapped({"value": 2}, document="Part7")

    assert result["warning"] == "own. Beta. Shared."


@pytest.mark.parametrize("notice", [None, "", Mock()])
async def test_no_notice_adds_nothing(notice: Any) -> None:
    wrapped = tool_boundary(_tool, adapter=_adapter(notice))

    assert (await wrapped({"value": 2}))["warning"] == "own."


async def test_without_an_adapter_there_is_no_document_argument() -> None:
    plain = tool_boundary(_tool)

    assert "document" not in inspect.signature(plain).parameters
    assert (
        "document"
        in inspect.signature(tool_boundary(_tool, adapter=_adapter(None))).parameters
    )


async def test_a_notice_without_a_level_or_own_warning() -> None:
    async def quiet(input_data: _In) -> dict[str, Any]:
        return {"status": "success", "message": "ok"}

    quiet.__module__ = "solidworks_mcp.tools.modeling"

    result = await tool_boundary(quiet, adapter=_adapter("Shared."))({})

    assert result["warning"] == "Shared."


def test_a_registrar_given_the_adapter_later_keeps_it() -> None:
    registrar = ToolRegistrar.of(FastMCP("x"))
    adapter = object()

    assert ToolRegistrar.of(registrar, adapter) is registrar
    assert registrar._adapter is adapter
    assert ToolRegistrar.of(registrar, object())._adapter is adapter


async def test_document_alone_is_not_an_input(mock_config: Any) -> None:
    """``list_components`` takes ``document`` but no input of its own."""
    _adapter, mcp, _titles = await _two_parts(mock_config)
    tools = {t.name: t.fn for t in await mcp.list_tools()}

    assert "document" in inspect.signature(tools["list_components"]).parameters
    assert takes_input(tools["list_components"]) is False
    assert takes_input(tools["rebuild_model"]) is True
