"""Refusing to work on a document someone else made active.

Two clients driving one SolidWorks (or a user switching documents in the UI)
change which document is active between this session's calls. The next call
would then act on their document, so ``_handle_com_operation`` refuses it
until the session says which document to work on (``activate_document``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.tools.error_classifier import ErrorClassifier


class _Doc:
    def __init__(self, title: Any, path: Any = "") -> None:
        self.title = title
        self.path = path

    def GetTitle(self) -> Any:  # noqa: N802 - COM name
        return self.title

    def GetPathName(self) -> Any:  # noqa: N802
        return self.path


OURS = _Doc("Part14")
THEIRS = _Doc("DishRack_SideBar.SLDPRT", r"C:\Users\someone\DishRack_SideBar.SLDPRT")


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> PyWin32Adapter:
    """Connected (no window), working on ``OURS``, which is active."""
    monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(pywin32_adapter.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        pywin32_adapter, "pywintypes", SimpleNamespace(com_error=RuntimeError)
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS", "0")
    adapter = PyWin32Adapter({})
    adapter.swApp = SimpleNamespace(ActiveDoc=OURS, RevisionNumber="34.4.1")
    adapter.currentModel = OURS
    return adapter


def _never_run() -> None:
    raise AssertionError("the operation ran")


def _switch_to(adapter: PyWin32Adapter, document: Any) -> None:
    """The user or another client activates ``document``."""
    adapter.swApp.ActiveDoc = document  # type: ignore[union-attr]


def test_the_first_call_runs_and_remembers_the_active_document(
    adapter: PyWin32Adapter,
) -> None:
    assert adapter._handle_com_operation("add_line", lambda: "line").is_success

    assert adapter._active_document_seen is True
    assert adapter._last_active_document == ("", "Part14")


def test_calls_run_while_the_active_document_stays(adapter: PyWin32Adapter) -> None:
    adapter._handle_com_operation("add_line", lambda: None)

    assert adapter._handle_com_operation("add_circle", lambda: "c").is_success


def test_a_call_after_someone_switched_documents_is_refused(
    adapter: PyWin32Adapter,
) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    _switch_to(adapter, THEIRS)

    result = adapter._handle_com_operation("add_fillet", _never_run)

    assert result.is_error
    message = str(result.error)
    assert "it is now 'DishRack_SideBar.SLDPRT'" in message
    assert "add_fillet was not run" in message
    assert "working on 'Part14'" in message
    assert "activate_document with 'Part14'" in message
    assert ErrorClassifier().classify(message).error_type == "active_document_changed"


def test_it_stays_refused_until_a_document_is_chosen(adapter: PyWin32Adapter) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    _switch_to(adapter, THEIRS)
    adapter._handle_com_operation("add_fillet", _never_run)

    assert adapter._handle_com_operation("get_model_info", _never_run).is_error

    def activate() -> str:
        _switch_to(adapter, OURS)
        return "Part14"

    assert adapter._handle_com_operation("activate_document", activate).is_success
    assert adapter._handle_com_operation("add_fillet", lambda: "f").is_success


@pytest.mark.parametrize(
    "operation",
    sorted(pywin32_adapter._DOCUMENT_CHOOSING_OPERATIONS),
)
def test_operations_that_choose_a_document_always_run(
    adapter: PyWin32Adapter, operation: str
) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    _switch_to(adapter, THEIRS)

    assert adapter._handle_com_operation(operation, lambda: "ran").data == "ran"


def test_choosing_the_other_document_works_on_it(adapter: PyWin32Adapter) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    _switch_to(adapter, THEIRS)

    def activate() -> None:
        adapter.currentModel = THEIRS

    adapter._handle_com_operation("activate_document", activate)

    assert adapter._handle_com_operation("add_fillet", lambda: "f").is_success


def test_a_document_this_session_activated_is_not_a_switch(
    adapter: PyWin32Adapter,
) -> None:
    """An operation that changes the active document itself (a drawing view
    export, an assembly insert) leaves it active for the next call."""

    def switches_itself() -> None:
        _switch_to(adapter, THEIRS)

    adapter._handle_com_operation("export_file", switches_itself)

    assert adapter._handle_com_operation("add_line", lambda: "l").is_success


def test_a_session_with_no_document_takes_whatever_is_active(
    adapter: PyWin32Adapter,
) -> None:
    adapter._handle_com_operation("close_model", lambda: None)
    adapter.currentModel = None
    _switch_to(adapter, THEIRS)

    assert adapter._handle_com_operation("get_model_info", lambda: "i").is_success


def test_nothing_active_any_more_is_a_switch(adapter: PyWin32Adapter) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    _switch_to(adapter, None)

    result = adapter._handle_com_operation("add_line", _never_run)

    assert "no document is active now" in str(result.error)


def test_nested_operations_are_not_checked(adapter: PyWin32Adapter) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    _switch_to(adapter, THEIRS)
    adapter._operation_depth = 1

    assert adapter._handle_com_operation("inner", lambda: 1).is_success


def test_without_solidworks_nothing_is_checked_or_remembered(
    adapter: PyWin32Adapter,
) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    adapter.swApp = None

    adapter._handle_com_operation("add_line", lambda: None)

    assert adapter._last_active_document == ("", "Part14")
    assert adapter._active_document_switched("add_line") is None


def test_documents_that_cant_be_named_compare_equal(adapter: PyWin32Adapter) -> None:
    unreadable = _Doc(object(), object())
    adapter.currentModel = unreadable
    _switch_to(adapter, unreadable)
    adapter._handle_com_operation("create_sketch", lambda: None)
    _switch_to(adapter, _Doc(object(), object()))

    assert adapter._handle_com_operation("add_line", lambda: "l").is_success


@pytest.mark.parametrize(
    ("key", "label"),
    [
        (None, "no document"),
        (("", "Part14"), "'Part14'"),
        ((r"c:\work\bracket.sldprt", ""), "'bracket.sldprt'"),
        (("", ""), "an unnamed document"),
    ],
)
def test_document_label(key: tuple[str, str] | None, label: str) -> None:
    assert PyWin32Adapter._document_label(key) == label


def test_a_saved_document_is_known_by_its_path(adapter: PyWin32Adapter) -> None:
    key = adapter._document_key(_Doc("Bracket", r"C:\Work\Bracket.SLDPRT "))

    assert key is not None
    assert key[0].endswith("bracket.sldprt") or key[0].endswith("Bracket.SLDPRT")
    assert key[1] == "Bracket"


def test_forgetting_documents_forgets_the_active_one(adapter: PyWin32Adapter) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)

    adapter._session_coordinator.forget_documents()

    assert adapter._active_document_seen is False
    assert adapter._last_active_document is None


async def test_disconnect_forgets_the_active_document(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter._handle_com_operation("create_sketch", lambda: None)
    monkeypatch.setattr(
        adapter._session_coordinator, "uninitialize_com_apartment", lambda: None
    )

    await adapter.disconnect()

    assert adapter._active_document_seen is False
    assert adapter._last_active_document is None
