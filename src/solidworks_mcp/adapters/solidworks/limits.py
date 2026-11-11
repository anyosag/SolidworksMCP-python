"""Limits on how long SolidWorks work runs, and what happens when the client goes.

Seen with the Cellvis dish rack: a client was killed during ``add_fillet``'s
edge walk. The server kept walking edges for the dead client, SolidWorks sat
at 100% CPU, and the next two calls from a new client (``rename_feature``)
each waited 1800 s for a SolidWorks that never answered.

Every COM call runs on the server's event-loop thread, so while one runs the
server can neither read a cancel nor send progress, and pywin32 has no
``CoCancelCall`` to abandon a call already made. What can be done, and is
here:

* **A time limit for the server's own loops.** ``_handle_com_operation``
  starts a budget for each outermost operation
  (``SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS``, default 900; 0 turns it
  off). Loops that make many COM calls (edge walks, outlines, ray casts)
  call :func:`check` between calls and stop with a clear error when it runs
  out.
* **Stopping when the client has gone.** :func:`watch_stdin` watches the
  stdio pipe from its own thread with ``PeekNamedPipe``, which reads nothing;
  when the client end closes, :func:`check` stops the loop at its next call,
  so a dead client's work ends within one COM call
  (``SOLIDWORKS_MCP_WATCH_CLIENT=0`` turns the watcher off).
* **Not calling a SolidWorks that doesn't answer.** :func:`wait_until_responsive`
  asks SolidWorks' frame window (Win32 only, never COM) whether its UI thread
  answers. A SolidWorks busy with someone else's long call is given
  ``SOLIDWORKS_MCP_BUSY_WAIT_SECONDS`` (default 30) to finish; after that the
  call is refused at once as ``solidworks_busy`` instead of hanging.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

DEFAULT_OPERATION_TIMEOUT_S = 900.0
DEFAULT_BUSY_WAIT_S = 30.0

#: ``GetStdHandle(STD_INPUT_HANDLE)``, ``GetFileType``'s pipe value, and the
#: errors ``PeekNamedPipe`` gives once the other end of the pipe has closed.
_STD_INPUT_HANDLE = -10
_FILE_TYPE_PIPE = 3
_PIPE_CLOSED_ERRORS = frozenset({109, 232, 233})  # BROKEN_PIPE, NO_DATA, NOT_CONNECTED


class OperationStopped(Exception):
    """A loop stopped because its time ran out or the client went away."""


def _seconds_from_env(name: str, default: float) -> float:
    """A non-negative number of seconds from the environment, else ``default``."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("{}={!r} is not a number; using {}", name, raw, default)
        return default
    return max(0.0, value)


def operation_timeout_seconds() -> float:
    """``SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS`` (0 means no limit)."""
    return _seconds_from_env(
        "SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS", DEFAULT_OPERATION_TIMEOUT_S
    )


def busy_wait_seconds() -> float:
    """``SOLIDWORKS_MCP_BUSY_WAIT_SECONDS``: how long to wait for a busy SolidWorks."""
    return _seconds_from_env("SOLIDWORKS_MCP_BUSY_WAIT_SECONDS", DEFAULT_BUSY_WAIT_S)


def watching_enabled() -> bool:
    """``SOLIDWORKS_MCP_WATCH_CLIENT``: whether :func:`watch_stdin` runs (default yes)."""
    raw = os.environ.get("SOLIDWORKS_MCP_WATCH_CLIENT", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


@dataclass
class _Budget:
    operation: str
    started: float
    limit: float


_state: dict[str, Any] = {"budget": None, "client_gone": None}
_client_gone = threading.Event()


def begin(operation: str, clock: Callable[[], float] = time.monotonic) -> None:
    """Start the time budget for an outermost operation."""
    _state["budget"] = _Budget(operation, clock(), operation_timeout_seconds())


def end() -> None:
    """End the current operation's budget."""
    _state["budget"] = None


def mark_client_gone(reason: str) -> None:
    """Record that the client has gone; loops stop at their next check."""
    if not _client_gone.is_set():
        logger.warning("MCP client gone ({}); stopping SolidWorks loops", reason)
        _state["client_gone"] = reason
        _client_gone.set()


def client_gone() -> bool:
    """Whether the client has gone (see :func:`watch_stdin`)."""
    return _client_gone.is_set()


def reset() -> None:
    """Forget the budget and the client's state (tests, and a new session)."""
    _state["budget"] = None
    _state["client_gone"] = None
    _client_gone.clear()


def check(doing: str, clock: Callable[[], float] = time.monotonic) -> None:
    """Stop a loop when the client has gone or its operation is out of time.

    Call it between the COM calls of a loop that makes many.

    Args:
        doing: What the loop is doing, for the message ("picking edges").
        clock: The monotonic clock (tests pass a fake).

    Raises:
        OperationStopped: With a message saying why and what to do.
    """
    if _client_gone.is_set():
        raise OperationStopped(
            f"Stopped {doing}: the MCP client disconnected "
            f"({_state['client_gone']}), so nothing would read the result."
        )
    budget = _state["budget"]
    if budget is None or not budget.limit:
        return
    spent = clock() - budget.started
    if spent > budget.limit:
        raise OperationStopped(
            f"Stopped {doing} after {spent:.0f} s: {budget.operation} ran past "
            f"its {budget.limit:.0f} s limit (SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS). "
            "Do it in smaller pieces, or raise the limit."
        )


def wait_until_responsive(
    is_responding: Callable[[], bool],
    seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    poll: float = 0.5,
) -> float | None:
    """Wait for SolidWorks to answer window messages again.

    Args:
        is_responding: Asks SolidWorks' frame window (Win32, no COM).
        seconds: How long to wait at most.
        sleep: ``time.sleep`` (tests pass a fake).
        clock: The monotonic clock (tests pass a fake).
        poll: Seconds between asks.

    Returns:
        float | None: Seconds waited (0 when it answered at once), or None
        when it still doesn't answer after ``seconds``.
    """
    started = clock()
    while True:
        if is_responding():
            return clock() - started
        if clock() - started >= seconds or _client_gone.is_set():
            return None
        sleep(poll)


def _kernel32(platform: str | None = None, loader: Any = None) -> Any | None:
    """``kernel32`` with the signatures :func:`watch_stdin` uses, or None off Windows."""
    if (platform or sys.platform) != "win32":
        return None
    dll = (loader or ctypes.WinDLL)("kernel32", use_last_error=True)
    dll.GetStdHandle.argtypes = [ctypes.c_ulong]
    dll.GetStdHandle.restype = ctypes.c_void_p
    dll.GetFileType.argtypes = [ctypes.c_void_p]
    dll.GetFileType.restype = ctypes.c_ulong
    dll.PeekNamedPipe.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_void_p,
    ]
    dll.PeekNamedPipe.restype = ctypes.c_int
    return dll


def stdin_closed(
    kernel32: Any,
    handle: Any,
    last_error: Callable[[], int] = ctypes.get_last_error,
) -> bool:
    """Whether the client end of the stdin pipe has closed (reads nothing)."""
    available = ctypes.c_ulong(0)
    if kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
        return False
    return last_error() in _PIPE_CLOSED_ERRORS


def watch_stdin(
    kernel32: Any = None,
    interval: float = 1.0,
    platform: str | None = None,
    last_error: Callable[[], int] = ctypes.get_last_error,
) -> threading.Thread | None:
    """Watch the stdio pipe from a daemon thread; mark the client gone when it closes.

    Only for a stdin that is a pipe (how MCP clients run a stdio server); a
    console or a file is not watched.

    Args:
        kernel32: A ``kernel32``-like object (tests pass a fake).
        interval: Seconds between peeks.
        platform: ``sys.platform`` (tests pass another value).
        last_error: ``ctypes.get_last_error`` (tests pass a fake).

    Returns:
        threading.Thread | None: The watcher, or None when nothing is watched.
    """
    if not watching_enabled():
        return None
    dll = kernel32 if kernel32 is not None else _kernel32(platform)
    if dll is None:
        return None
    handle = dll.GetStdHandle(_STD_INPUT_HANDLE & 0xFFFFFFFF)
    if not handle or dll.GetFileType(handle) != _FILE_TYPE_PIPE:
        return None

    def _run() -> None:
        while not _client_gone.is_set():
            if stdin_closed(dll, handle, last_error):
                mark_client_gone("its end of the stdio pipe closed")
                return
            time.sleep(interval)

    thread = threading.Thread(target=_run, name="mcp-client-watch", daemon=True)
    thread.start()
    return thread
