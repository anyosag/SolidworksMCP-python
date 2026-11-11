"""The session register: which document each MCP server is working on."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import sessions
from solidworks_mcp.adapters.solidworks.sessions import (
    SessionRegister,
    process_alive,
    same_document,
    session_directory,
    shared_document_notice,
)

SW = 9396
PART = ("c:\\work\\bracket.sldprt", "bracket.SLDPRT")


def _register(
    directory: Path, pid: int, alive: set[int] | None = None
) -> SessionRegister:
    living = {pid} if alive is None else alive
    return SessionRegister(
        directory, pid=pid, alive=lambda p: p in living, clock=lambda: 5.0
    )


def test_the_directory_is_under_local_app_data_unless_set() -> None:
    assert session_directory({"SOLIDWORKS_MCP_SESSION_DIR": "D:\\s"}) == Path("D:\\s")
    assert session_directory({"LOCALAPPDATA": "C:\\L"}) == Path(
        "C:\\L", "solidworks_mcp", "sessions"
    )
    assert session_directory({}) == Path.home() / "solidworks_mcp" / "sessions"
    assert session_directory() == Path(os.environ["SOLIDWORKS_MCP_SESSION_DIR"])


def test_a_server_records_its_document(tmp_path: Path) -> None:
    register = _register(tmp_path, 11)

    register.record(SW, PART)

    assert json.loads((tmp_path / "11.json").read_text()) == {
        "pid": 11,
        "solidworks_pid": SW,
        "path": PART[0],
        "title": PART[1],
        "updated": 5.0,
    }
    register.record(SW, None)
    assert json.loads((tmp_path / "11.json").read_text())["title"] == ""
    register.forget()
    assert not (tmp_path / "11.json").exists()
    register.forget()  # already gone


def test_a_record_that_cannot_be_written_is_skipped(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")

    _register(blocker, 11).record(SW, PART)  # no exception

    assert blocker.read_text() == "not a directory"


def test_another_live_server_on_the_same_document_is_found(tmp_path: Path) -> None:
    alive = {11, 22, 33, 44}
    _register(tmp_path, 22, alive).record(SW, PART)
    _register(tmp_path, 33, alive).record(SW, ("", "Part7"))
    _register(tmp_path, 44, alive).record(1234, PART)  # another SolidWorks
    me = _register(tmp_path, 11, alive)
    me.record(SW, PART)

    others = me.others_on(SW, PART)

    assert [entry["pid"] for entry in others] == [22]
    assert me.others_on(SW, None) == []
    assert me.others_on(SW, ("", "")) == []
    assert me.others_on(0, PART) == []  # SolidWorks process unknown


def test_files_of_servers_that_exited_are_deleted(tmp_path: Path) -> None:
    _register(tmp_path, 22, {22}).record(SW, PART)
    (tmp_path / "junk.json").write_text("{not json")
    (tmp_path / "list.json").write_text("[1, 2]")
    me = _register(tmp_path, 11, {11})

    assert me.others_on(SW, PART) == []
    assert not (tmp_path / "22.json").exists()
    assert (tmp_path / "junk.json").exists()  # unreadable: left alone


def test_a_file_that_cannot_be_deleted_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(tmp_path, 22, {22}).record(SW, PART)

    def locked(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "unlink", locked)

    assert _register(tmp_path, 11, {11}).others_on(SW, PART) == []
    _register(tmp_path, 22, {22}).forget()


@pytest.mark.parametrize(
    ("entry", "key", "same"),
    [
        ({"path": "C:\\Work\\Bracket.SLDPRT"}, PART, True),
        ({"path": "c:\\other.sldprt", "title": PART[1]}, PART, False),
        ({"path": "", "title": "Part7"}, ("c:\\x.sldprt", "Part7"), True),
        ({"path": "", "title": "Part7"}, ("", ""), False),
        ({}, ("", "Part8"), False),
    ],
)
def test_documents_match_by_path_else_title(
    entry: dict[str, Any], key: tuple[str, str], same: bool
) -> None:
    assert same_document(entry, key) is same


def test_the_notice_names_the_other_servers() -> None:
    assert shared_document_notice("'Part7'", []) is None
    one = shared_document_notice("'Part7'", [{"pid": 22}])
    two = shared_document_notice("'Part7'", [{"pid": 22}, {"pid": 33}])

    assert one is not None and one.startswith(
        "Another MCP server (process 22) is also working on 'Part7'"
    )
    assert two is not None and two.startswith("2 other MCP servers (process 22, 33)")


class _Kernel32:
    def __init__(self, handle: int, code: int = 259, read: bool = True) -> None:
        self.handle, self.code, self.read = handle, code, read
        self.closed: list[int] = []

    def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:  # noqa: N802
        assert access == 0x1000 and inherit is False
        return self.handle

    def GetExitCodeProcess(self, handle: int, code: Any) -> int:  # noqa: N802
        code._obj.value = self.code
        return int(self.read)

    def CloseHandle(self, handle: int) -> int:  # noqa: N802
        self.closed.append(handle)
        return 1


@pytest.mark.parametrize(
    ("kernel32", "alive"),
    [
        (_Kernel32(7, 259), True),
        (_Kernel32(7, 0), False),
        (_Kernel32(7, read=False), True),
    ],
)
def test_a_process_is_alive_while_it_has_no_exit_code(
    kernel32: _Kernel32, alive: bool
) -> None:
    assert process_alive(42, kernel32, platform="win32") is alive
    assert kernel32.closed == [7]


@pytest.mark.parametrize(("error", "alive"), [(5, True), (87, False)])
def test_a_process_that_cannot_be_opened(
    monkeypatch: pytest.MonkeyPatch, error: int, alive: bool
) -> None:
    monkeypatch.setattr(sessions.ctypes, "get_last_error", lambda: error)

    assert process_alive(42, _Kernel32(0), platform="win32") is alive


def test_this_process_is_alive_and_nonsense_is_not() -> None:
    assert process_alive(os.getpid()) is True
    assert process_alive(0) is False


@pytest.mark.parametrize(
    ("raised", "alive"),
    [(None, True), (ProcessLookupError, False), (PermissionError, True)],
)
def test_elsewhere_a_null_signal_asks(
    monkeypatch: pytest.MonkeyPatch, raised: type[Exception] | None, alive: bool
) -> None:
    def kill(pid: int, signal: int) -> None:
        assert signal == 0
        if raised is not None:
            raise raised()

    monkeypatch.setattr(sessions.os, "kill", kill)

    assert process_alive(42, platform="linux") is alive
