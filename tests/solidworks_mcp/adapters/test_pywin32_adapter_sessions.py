"""The adapter records its document, and warns once when another server shares it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import window as window_module
from solidworks_mcp.adapters.solidworks.sessions import SessionRegister

SW = 9396


@pytest.fixture(autouse=True)
def _no_keepers() -> Iterator[None]:
    yield
    for keeper in list(window_module._KEEPERS.values()):
        keeper.stop()
    window_module._KEEPERS.clear()


class _Doc:
    def __init__(self, title: str, path: str = "") -> None:
        self.title, self.path = title, path

    def GetTitle(self) -> str:  # noqa: N802 - COM name
        return self.title

    def GetPathName(self) -> str:  # noqa: N802 - COM name
        return self.path


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> PyWin32Adapter:
    monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(pywin32_adapter.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        pywin32_adapter, "pywintypes", SimpleNamespace(com_error=RuntimeError)
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("SOLIDWORKS_MCP_KEEP_MINIMIZED", "0")
    made = PyWin32Adapter({})
    made._sessions = SessionRegister(tmp_path, pid=11, alive=lambda pid: True)
    made._sw_process_id = SW
    made.swApp = SimpleNamespace(ActiveDoc=_Doc("Part7"))
    return made


def _other_server(directory: Path, title: str = "Part7") -> None:
    SessionRegister(directory, pid=22, alive=lambda pid: True).record(SW, ("", title))


def test_a_shared_document_is_warned_about_once(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    _other_server(tmp_path)

    assert adapter._handle_com_operation("add_line", lambda: 1).is_success
    notice = adapter.take_document_notice()
    adapter._handle_com_operation("add_line", lambda: 1)

    assert notice is not None
    assert "Another MCP server (process 22) is also working on 'Part7'" in notice
    assert adapter.take_document_notice() is None  # once
    assert (tmp_path / "11.json").exists()


def test_a_document_of_its_own_gets_no_warning(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    _other_server(tmp_path, "Part8")

    adapter._handle_com_operation("add_line", lambda: 1)

    assert adapter.take_document_notice() is None


def test_moving_to_the_shared_document_warns_then(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    adapter._handle_com_operation("add_line", lambda: 1)
    _other_server(tmp_path, "Part8")
    assert adapter.take_document_notice() is None

    adapter.swApp.ActiveDoc = _Doc("Part8")
    adapter._handle_com_operation("activate_document", lambda: 1)

    assert "'Part8'" in (adapter.take_document_notice() or "")


def test_a_broken_register_never_fails_a_call(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: Any) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(adapter._sessions, "record", broken)

    assert adapter._handle_com_operation("add_line", lambda: 1).is_success
    assert adapter.take_document_notice() is None


async def test_disconnect_removes_the_session_file(
    adapter: PyWin32Adapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter._handle_com_operation("add_line", lambda: 1)
    _other_server(tmp_path)
    adapter._document_notice = "pending"
    monkeypatch.setattr(adapter._session_coordinator, "disconnect", AsyncMock())

    await adapter.disconnect()

    assert not (tmp_path / "11.json").exists()
    assert (adapter._recorded_document, adapter.take_document_notice()) == (None, None)
