"""``measure_clearance`` on the PyWin32 side (``SolidWorksDocumentationMixin``).

The measuring itself is ``clearance.measure_clearance`` (``test_clearance``);
here: the document check, and how its errors read.
"""

from __future__ import annotations

from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import clearance
from solidworks_mcp.adapters.solidworks.documentation import (
    SolidWorksDocumentationMixin,
)


class _Doc:
    def __init__(self, doc_type: Any) -> None:
        self._type = doc_type

    def GetType(self) -> Any:  # noqa: N802
        return self._type


class _Harness(SolidWorksDocumentationMixin):
    """The mixin plus the PyWin32Adapter members it relies on."""

    def __init__(self, model: Any) -> None:
        self.currentModel = model
        self.swApp = None

    def _handle_com_operation(self, name: str, operation: Any, *args: Any) -> Any:
        try:
            data = operation(*args)
        except Exception as exc:  # noqa: BLE001 - mirrors PyWin32Adapter
            return AdapterResult(
                status=AdapterResultStatus.ERROR, error=f"Error in {name}: {exc}"
            )
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data=data)

    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001
            return default

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value


async def test_it_measures_in_an_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, str]] = []

    def measure(_adapter: Any, a: str, b: str) -> dict[str, Any]:
        asked.append((a, b))
        return {"clearance_mm": 0.25}

    monkeypatch.setattr(clearance, "measure_clearance", measure)

    result = await _Harness(_Doc(2)).measure_clearance("tongue-1", "slot-1")

    assert result.is_success, result.error
    assert result.data == {"clearance_mm": 0.25}
    assert asked == [("tongue-1", "slot-1")]


async def test_its_errors_read_without_the_operation_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args: Any) -> dict[str, Any]:
        raise clearance.InvalidRequest("component_b 'slot-1' is suppressed")

    monkeypatch.setattr(clearance, "measure_clearance", refuse)

    result = await _Harness(_Doc(2)).measure_clearance("tongue-1", "slot-1")

    assert result.error == "Invalid request: component_b 'slot-1' is suppressed"


@pytest.mark.parametrize(
    ("doc_type", "what"), [(1, "a part"), (3, "a drawing"), (None, "not one")]
)
async def test_another_document_is_an_invalid_request(doc_type: Any, what: str) -> None:
    result = await _Harness(_Doc(doc_type)).measure_clearance("a-1", "b-1")

    assert result.error == (
        "Invalid request: measure_clearance measures between components of an "
        f"assembly, and the active document is {what}; activate the assembly "
        "first."
    )


async def test_it_needs_an_active_model() -> None:
    result = await _Harness(None).measure_clearance("a-1", "b-1")

    assert result.error == "No active model"
