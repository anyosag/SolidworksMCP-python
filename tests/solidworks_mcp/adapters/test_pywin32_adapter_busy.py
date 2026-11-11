"""A busy SolidWorks is refused, and every operation runs inside a time budget.

From the Cellvis dish rack: after a client was killed mid-fillet, SolidWorks
sat at 100% CPU and the next two calls each waited 1800 s for it.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import limits
from solidworks_mcp.adapters.solidworks import window as window_module
from solidworks_mcp.adapters.solidworks.window import SolidWorksWindow
from solidworks_mcp.tools.error_classifier import ErrorClassifier

from .solidworks.fake_user32 import FakeUser32

FRAME = 0x1000


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    limits.reset()
    yield
    limits.reset()
    for keeper in list(window_module._KEEPERS.values()):
        keeper.stop()
    window_module._KEEPERS.clear()


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> PyWin32Adapter:
    monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(pywin32_adapter.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        pywin32_adapter, "pywintypes", SimpleNamespace(com_error=RuntimeError)
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("SOLIDWORKS_MCP_BUSY_WAIT_SECONDS", "0")
    monkeypatch.setenv("SOLIDWORKS_MCP_KEEP_MINIMIZED", "0")
    return PyWin32Adapter({})


def _attach(adapter: PyWin32Adapter, hung: bool) -> FakeUser32:
    user32 = FakeUser32()
    user32.add(FRAME, 9396, title="SOLIDWORKS", hung=hung)
    adapter._window = SolidWorksWindow(FRAME, user32)
    return user32


def test_a_busy_solidworks_is_refused_without_calling_it(
    adapter: PyWin32Adapter,
) -> None:
    _attach(adapter, hung=True)
    calls: list[str] = []

    result = adapter._handle_com_operation(
        "rename_feature", lambda: calls.append("ran")
    )

    assert result.is_error
    assert calls == []
    assert "SolidWorks is busy: it has not answered for 0 s" in (result.error or "")
    assert "rename_feature was not run" in (result.error or "")
    assert (
        ErrorClassifier().classify(result.error or "").error_type == "solidworks_busy"
    )


def test_an_answering_solidworks_runs_inside_a_budget(adapter: PyWin32Adapter) -> None:
    _attach(adapter, hung=False)
    seen: dict[str, Any] = {}

    def operation() -> str:
        seen["budget"] = limits._state["budget"]
        return "done"

    result = adapter._handle_com_operation("add_fillet", operation)

    assert result.is_success
    assert seen["budget"].operation == "add_fillet"
    assert limits._state["budget"] is None  # ended with the operation


def test_a_window_that_cannot_be_asked_does_not_block(adapter: PyWin32Adapter) -> None:
    adapter._window = SimpleNamespace(  # type: ignore[assignment]
        is_responding=lambda: (_ for _ in ()).throw(OSError("gone")),
        available=False,
        is_minimized=lambda: False,
        allow_activation=lambda: None,
    )

    assert adapter._handle_com_operation("add_line", lambda: 1).is_success


def test_a_late_answer_is_logged_and_the_call_runs(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    _attach(adapter, hung=False)
    monkeypatch.setattr(limits, "wait_until_responsive", lambda *_a, **_k: 2.5)

    assert adapter._refuse_while_busy("add_line") is None


def test_a_loop_out_of_time_becomes_an_operation_stopped_error(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS", "1")

    def slow_loop() -> None:
        limits._state["budget"].started -= 5  # as if 5 s had passed
        limits.check("picking edges")

    result = adapter._handle_com_operation("add_fillet", slow_loop)

    assert result.is_error
    assert "Stopped picking edges after 5 s" in (result.error or "")
    assert (
        ErrorClassifier().classify(result.error or "").error_type == "operation_stopped"
    )
