"""Which document each MCP server on this machine is working on.

Two MCP clients driving one SolidWorks take turns: each one that activates
its document makes the other's next call fail with ``active_document_changed``
(runbook #16). When both work on the *same* document neither sees that, and
their edits interleave in it. So each server writes the document it works on,
and the SolidWorks process it drives, to its own file
(``%LOCALAPPDATA%\\solidworks_mcp\\sessions\\<pid>.json``, or
``SOLIDWORKS_MCP_SESSION_DIR``). When a server starts on a document, it reads
the other files: another live server on the same SolidWorks and the same
document gets a warning in the reply. Files of servers that have exited are
deleted by whoever reads them next.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

#: OpenProcess access, GetExitCodeProcess' "still running", and OpenProcess'
#: error for a process that exists but may not be opened.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5

DocumentKey = tuple[str, str]


def session_directory(env: dict[str, str] | None = None) -> Path:
    """Where the session files live (``SOLIDWORKS_MCP_SESSION_DIR`` overrides)."""
    env = dict(os.environ) if env is None else env
    explicit = env.get("SOLIDWORKS_MCP_SESSION_DIR", "").strip()
    if explicit:
        return Path(explicit)
    base = env.get("LOCALAPPDATA", "").strip() or str(Path.home())
    return Path(base) / "solidworks_mcp" / "sessions"


def process_alive(pid: int, kernel32: Any = None, platform: str | None = None) -> bool:
    """Whether process ``pid`` is running (Windows: ``OpenProcess``; never signals it).

    ``os.kill(pid, 0)`` would terminate the process on Windows, so it is
    only used elsewhere.
    """
    if pid <= 0:
        return False
    if (platform or sys.platform) != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    dll = kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)
    handle = dll.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = ctypes.c_ulong(0)
        if not dll.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE
    finally:
        dll.CloseHandle(handle)


def _delete(file: Path) -> None:
    """Delete ``file``; one another process holds open is left for later."""
    with contextlib.suppress(OSError):
        file.unlink(missing_ok=True)


def same_document(a: dict[str, Any], key: DocumentKey) -> bool:
    """Whether a session entry names the document ``key`` (path, else title)."""
    path, title = key
    other_path = str(a.get("path") or "")
    if path and other_path:
        return os.path.normcase(other_path) == os.path.normcase(path)
    return bool(title) and str(a.get("title") or "") == title


class SessionRegister:
    """This server's session file, and the other servers' files.

    Args:
        directory: Where the files live.
        pid: This server's process id.
        alive: Whether a process id is running.
        clock: ``time.time`` (tests pass a fake).
    """

    def __init__(
        self,
        directory: Path,
        pid: int | None = None,
        alive: Callable[[int], bool] = process_alive,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.directory = directory
        self.pid = os.getpid() if pid is None else pid
        self._alive = alive
        self._clock = clock

    @property
    def path(self) -> Path:
        """This server's own file."""
        return self.directory / f"{self.pid}.json"

    def record(self, solidworks_pid: int, key: DocumentKey | None) -> None:
        """Write the document this server works on (``None``: none)."""
        path, title = key or ("", "")
        entry = {
            "pid": self.pid,
            "solidworks_pid": solidworks_pid,
            "path": path,
            "title": title,
            "updated": self._clock(),
        }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_suffix(".tmp")
            partial.write_text(json.dumps(entry), encoding="utf-8")
            partial.replace(self.path)
        except OSError as exc:
            logger.debug("Could not write session file {}: {}", self.path, exc)

    def forget(self) -> None:
        """Delete this server's file (on disconnect)."""
        _delete(self.path)

    def _entries(self) -> list[dict[str, Any]]:
        """The other servers' entries; files of exited servers are deleted."""
        entries = []
        for file in sorted(self.directory.glob("*.json")):
            if file == self.path:
                continue
            try:
                entry = json.loads(file.read_text(encoding="utf-8"))
                pid = int(entry["pid"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if not self._alive(pid):
                _delete(file)
                continue
            entries.append(entry)
        return entries

    def others_on(
        self, solidworks_pid: int, key: DocumentKey | None
    ) -> list[dict[str, Any]]:
        """Other live servers driving the same SolidWorks on the same document.

        Without a SolidWorks process id (its window was never found) nothing
        can be told apart, so nothing is reported.
        """
        if key is None or not any(key) or not solidworks_pid:
            return []
        return [
            entry
            for entry in self._entries()
            if entry.get("solidworks_pid") == solidworks_pid
            and same_document(entry, key)
        ]


def shared_document_notice(label: str, others: list[dict[str, Any]]) -> str | None:
    """The warning for a document other servers are also working on."""
    if not others:
        return None
    pids = ", ".join(str(entry["pid"]) for entry in others)
    who = (
        "Another MCP server" if len(others) == 1 else f"{len(others)} other MCP servers"
    )
    return (
        f"{who} (process {pids}) is also working on {label} in this "
        "SolidWorks, so its edits and this session's go into the same "
        "document. Make sure that is meant; otherwise give each client its "
        "own document, or its own SolidWorks."
    )
