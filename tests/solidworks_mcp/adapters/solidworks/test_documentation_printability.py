"""The live adapter's ``check_printability``: a part only, then ``check_part``."""

from __future__ import annotations

from typing import Any

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import print_check
from solidworks_mcp.adapters.solidworks.documentation import (
    SolidWorksDocumentationMixin,
)


class _Model:
    def __init__(self, doc_type: int) -> None:
        self._doc_type = doc_type

    def GetType(self) -> int:  # noqa: N802
        return self._doc_type


class _Harness(SolidWorksDocumentationMixin):
    def __init__(self, doc_type: int) -> None:
        self.currentModel = _Model(doc_type)
        self.swApp = None

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value

    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001 - mirror the real adapter
            return default


async def test_a_part_is_checked(monkeypatch) -> None:
    calls: list[tuple[Any, ...]] = []

    async def check_part(adapter: Any, *args: Any) -> AdapterResult[dict[str, Any]]:
        calls.append((adapter, *args))
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data={"ok": True})

    monkeypatch.setattr(print_check, "check_part", check_part)
    harness = _Harness(1)

    result = await harness.check_printability("-y", 40.0, 8.0)

    assert result.data == {"ok": True}
    assert calls == [(harness, "-y", 40.0, 8.0)]


async def test_an_assembly_is_refused() -> None:
    result = await _Harness(2).check_printability("z")

    assert result.error == (
        "check_printability needs an active part document (active document is "
        "assembly)."
    )
