"""Time limits, the client-gone flag and waiting for a busy SolidWorks (``limits``)."""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import limits


@pytest.fixture(autouse=True)
def _fresh_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SOLIDWORKS_MCP_WATCH_CLIENT", "1")
    limits.reset()
    yield
    limits.reset()


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 900.0), ("", 900.0), ("60", 60.0), ("-5", 0.0), ("soon", 900.0)],
)
def test_the_operation_limit_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: float
) -> None:
    if raw is None:
        monkeypatch.delenv("SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS", raw)

    assert limits.operation_timeout_seconds() == expected


def test_the_busy_wait_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLIDWORKS_MCP_BUSY_WAIT_SECONDS", "4")
    assert limits.busy_wait_seconds() == 4.0
    monkeypatch.delenv("SOLIDWORKS_MCP_BUSY_WAIT_SECONDS")
    assert limits.busy_wait_seconds() == limits.DEFAULT_BUSY_WAIT_S


def test_a_loop_stops_when_its_operation_runs_out_of_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS", "60")
    clock = _Clock()
    limits.begin("add_fillet", clock)

    limits.check("picking edges", clock)  # in time
    clock.now += 61
    with pytest.raises(limits.OperationStopped) as stopped:
        limits.check("picking edges", clock)

    assert str(stopped.value).startswith("Stopped picking edges after 61 s: add_fillet")
    assert "ran past its 60 s limit" in str(stopped.value)
    limits.end()
    limits.check("picking edges", clock)  # no operation, no limit


def test_a_limit_of_zero_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS", "0")
    clock = _Clock()
    limits.begin("add_fillet", clock)
    clock.now += 100000

    limits.check("picking edges", clock)


def test_a_loop_stops_when_the_client_has_gone() -> None:
    limits.mark_client_gone("its end of the stdio pipe closed")
    limits.mark_client_gone("again")  # the first reason stays

    assert limits.client_gone()
    with pytest.raises(limits.OperationStopped, match="the MCP client disconnected"):
        limits.check("drawing outlines")
    with pytest.raises(limits.OperationStopped, match="stdio pipe closed"):
        limits.check("drawing outlines")


def test_waiting_for_solidworks_to_answer() -> None:
    clock = _Clock()
    answers = iter([False, False, True])
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.now += seconds

    waited = limits.wait_until_responsive(lambda: next(answers), 10, sleep, clock)

    assert waited == 1.0
    assert slept == [0.5, 0.5]
    assert limits.wait_until_responsive(lambda: True, 10, sleep, clock) == 0.0


def test_a_solidworks_that_never_answers_is_given_up_on() -> None:
    clock = _Clock()

    def sleep(seconds: float) -> None:
        clock.now += seconds

    assert limits.wait_until_responsive(lambda: False, 2, sleep, clock) is None
    limits.mark_client_gone("test")
    assert limits.wait_until_responsive(lambda: False, 60, sleep, clock) is None


class _Kernel32:
    """``GetStdHandle``, ``GetFileType`` and ``PeekNamedPipe`` on a fake pipe."""

    def __init__(self, file_type: int = 3, handle: int = 7, open_for: int = 1) -> None:
        self.file_type, self.handle = file_type, handle
        self.open_for = open_for
        self.peeks = 0

    def GetStdHandle(self, which: int) -> int:  # noqa: N802
        assert which == 0xFFFFFFF6
        return self.handle

    def GetFileType(self, handle: int) -> int:  # noqa: N802
        return self.file_type

    def PeekNamedPipe(self, handle: Any, *_args: Any) -> int:  # noqa: N802
        self.peeks += 1
        return int(self.peeks <= self.open_for)


@pytest.mark.parametrize(("error", "closed"), [(109, True), (233, True), (5, False)])
def test_a_closed_pipe_is_told_apart_from_other_errors(
    error: int, closed: bool
) -> None:
    kernel32 = _Kernel32(open_for=0)

    assert limits.stdin_closed(kernel32, 7, lambda: error) is closed
    assert limits.stdin_closed(_Kernel32(open_for=1), 7, lambda: 109) is False


def test_the_watcher_marks_the_client_gone_when_the_pipe_closes() -> None:
    kernel32 = _Kernel32(open_for=1)

    thread = limits.watch_stdin(kernel32, interval=0.01, last_error=lambda: 109)
    assert isinstance(thread, threading.Thread)
    thread.join(timeout=5)

    assert limits.client_gone()


@pytest.mark.parametrize("kernel32", [_Kernel32(file_type=2), _Kernel32(handle=0)])
def test_only_a_pipe_is_watched(kernel32: _Kernel32) -> None:
    assert limits.watch_stdin(kernel32) is None


@pytest.mark.parametrize("value", ["0", "off", "false"])
def test_the_watcher_can_be_turned_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SOLIDWORKS_MCP_WATCH_CLIENT", value)
    kernel32 = _Kernel32()

    assert limits.watching_enabled() is False
    assert limits.watch_stdin(kernel32) is None
    assert kernel32.peeks == 0


def test_nothing_is_watched_off_windows() -> None:
    assert limits.watch_stdin(platform="linux") is None
    assert limits._kernel32("linux") is None


def test_kernel32_gets_its_signatures() -> None:
    functions = {
        name: SimpleNamespace()
        for name in ("GetStdHandle", "GetFileType", "PeekNamedPipe")
    }
    loader = lambda _name, use_last_error: SimpleNamespace(**functions)  # noqa: E731

    dll = limits._kernel32("win32", loader)

    assert dll.PeekNamedPipe.restype is ctypes.c_int
    assert dll.GetStdHandle.restype is ctypes.c_void_p
