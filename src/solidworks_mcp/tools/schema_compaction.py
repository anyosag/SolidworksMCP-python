"""Smaller tool schemas in ``tools/list``, without changing what a call accepts.

Every tool definition the client lists goes into the agent's context, so its
size costs tokens on every turn that misses the prompt cache. Two patterns in
the schemas pydantic generates carry no information an agent needs:

* An optional field is written ``anyOf: [{type: X}, {type: "null"}]`` with
  ``default: null``. Advertising plain ``{type: X}`` says the same thing to an
  agent, which simply leaves the field out.
* Input aliases (``start_x`` beside ``x1``) are optional duplicates kept so old
  callers still work. They stay accepted; they just aren't advertised.

Only the *listed* schema changes. FastMCP validates a call against the tool
function's own pydantic types, so a client that still sends ``null`` or an
alias gets exactly the behaviour it had before.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from fastmcp.server.transforms import Transform
from fastmcp.tools.base import Tool

#: A short field description naming the field an alias ("Start point X alias").
_ALIAS_DESCRIPTION = re.compile(r"\balias\b", re.IGNORECASE)
_NULL = {"type": "null"}


def _is_alias(field_schema: Any) -> bool:
    """Whether a property's schema describes it as an input alias."""
    if not isinstance(field_schema, dict):
        return False
    description = str(field_schema.get("description") or "")
    return len(description) < 60 and bool(_ALIAS_DESCRIPTION.search(description))


def compact_schema(schema: Any) -> Any:
    """Return ``schema`` with nullable wrappers and alias properties removed.

    Args:
        schema: A JSON schema (or any part of one).

    Returns:
        Any: A new schema; the input is not modified.
    """
    if isinstance(schema, list):
        return [compact_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    compacted = {key: compact_schema(value) for key, value in schema.items()}

    options = compacted.get("anyOf")
    if isinstance(options, list) and len(options) == 2 and _NULL in options:
        (other,) = [option for option in options if option != _NULL]
        del compacted["anyOf"]
        compacted = {**other, **compacted}
        if "default" in compacted and compacted["default"] is None:
            del compacted["default"]

    properties = compacted.get("properties")
    if isinstance(properties, dict):
        required = set(compacted.get("required") or ())
        compacted["properties"] = {
            name: field
            for name, field in properties.items()
            if name in required or not _is_alias(field)
        }
    return compacted


class CompactToolSchemas(Transform):
    """List every tool with :func:`compact_schema` applied to its input schema."""

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        """Return copies of ``tools`` with compacted input schemas."""
        return [
            tool.model_copy(update={"parameters": compact_schema(tool.parameters)})
            for tool in tools
        ]
