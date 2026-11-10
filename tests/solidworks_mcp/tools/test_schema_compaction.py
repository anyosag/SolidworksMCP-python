"""Listed tool schemas drop nullable wrappers and input aliases.

Only what ``tools/list`` advertises changes; a call is still validated against
the tool function's own pydantic types.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from solidworks_mcp.tools.schema_compaction import CompactToolSchemas, compact_schema


def test_a_nullable_field_becomes_its_plain_type() -> None:
    schema = {
        "anyOf": [{"type": "number"}, {"type": "null"}],
        "default": None,
        "description": "Depth in mm",
    }

    assert compact_schema(schema) == {"type": "number", "description": "Depth in mm"}


def test_a_real_default_is_kept() -> None:
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}], "default": "Blind"}

    assert compact_schema(schema) == {"type": "string", "default": "Blind"}


def test_a_union_of_two_real_types_is_left_alone() -> None:
    schema = {"anyOf": [{"type": "number"}, {"type": "string"}]}

    assert compact_schema(schema) == schema


def test_optional_aliases_are_dropped_but_required_fields_kept() -> None:
    schema = {
        "type": "object",
        "required": ["x1"],
        "properties": {
            "x1": {"type": "number", "description": "Start X alias"},
            "start_x": {"type": "number", "description": "Start point X alias"},
            "note": {
                "type": "string",
                "description": "A long description that happens to mention an "
                "alias somewhere in the middle of a real sentence",
            },
        },
    }

    compacted = compact_schema(schema)

    assert set(compacted["properties"]) == {"x1", "note"}


def test_nested_schemas_and_lists_are_compacted() -> None:
    schema = {
        "properties": {
            "input_data": {
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    }
                }
            }
        },
        "examples": [{"anyOf": [{"type": "boolean"}, {"type": "null"}]}],
    }

    compacted = compact_schema(schema)

    inner = compacted["properties"]["input_data"]["properties"]["items"]
    assert inner["items"] == {"type": "integer"}
    assert compacted["examples"] == [{"type": "boolean"}]


def test_the_input_is_not_modified() -> None:
    schema = {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None}

    compact_schema(schema)

    assert schema == {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None}


class _LineInput(BaseModel):
    x1: float | None = Field(default=None, description="Start X in mm")
    start_x: float | None = Field(default=None, description="Start X alias")


@pytest.mark.asyncio
async def test_listing_is_compact_and_calls_still_accept_aliases_and_nulls() -> None:
    mcp = FastMCP("compaction")

    @mcp.tool()
    async def draw(input_data: _LineInput) -> dict:
        """Draw a line."""
        return {"x": input_data.x1 if input_data.x1 is not None else input_data.start_x}

    mcp.add_transform(CompactToolSchemas())

    (tool,) = await mcp.list_tools()
    listed = tool.parameters
    fields = (
        listed.get("$defs", {}).get("_LineInput", {}).get("properties")
        or (listed["properties"]["input_data"]["properties"])
    )
    assert fields == {"x1": {"type": "number", "description": "Start X in mm"}}

    by_alias = await mcp.call_tool("draw", {"input_data": {"start_x": 4}})
    with_null = await mcp.call_tool("draw", {"input_data": {"x1": None, "start_x": 5}})
    assert by_alias.structured_content == {"x": 4.0}
    assert with_null.structured_content == {"x": 5.0}
