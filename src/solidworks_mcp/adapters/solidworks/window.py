"""The SolidWorks main window, read and changed through Win32 calls only.

The adapter keeps a minimized SolidWorks minimized while tools run (see the
``keep-solidworks-minimized`` OpenSpec change). Everything here goes through
``user32`` and never through COM, so it is safe on any thread: the COM rule
(every SolidWorks call on the thread that ran ``connect()``) does not apply to
plain window messages.

The window handle comes from the connected SolidWorks itself
(``ISldWorks.Frame`` -> ``IFrame.GetHWnd``), not from a process lookup, so a
second SolidWorks on the machine is never touched.

Measured on SOLIDWORKS 2026 SP4.1 (``tests/scripts/probe_minimized.py``):
``NewDocument`` and activating an assembly restore a minimized SolidWorks and
make it the foreground window, and it stays the foreground window after it is
minimized again. So minimizing is not enough: :meth:`give_focus_to` hands the
keyboard focus back to the window the user had.

Tests pass a fake ``user32`` object with the same function names; see
``tests/solidworks_mcp/adapters/solidworks/fake_user32.py``.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

# Extended window style that stops a window being activated (winuser.h).
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

# ShowWindow commands (winuser.h).
SW_SHOWNOACTIVATE = 4
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_RESTORE = 9

# A message that does nothing, and SendMessageTimeout's "wait only for this
# window" and "don't wait on a hung window" flags (winuser.h).
WM_NULL = 0x0000
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002

#: The values :meth:`SolidWorksWindow.state` returns.
WINDOW_STATES = ("minimized", "normal", "maximized", "hidden", "unknown")

# (name, argtypes, restype) for every user32 function this package calls.
_HWND = ctypes.c_void_p
_SIGNATURES: list[tuple[str, list[Any], Any]] = [
    ("IsWindow", [_HWND], ctypes.c_int),
    ("IsWindowVisible", [_HWND], ctypes.c_int),
    ("IsWindowEnabled", [_HWND], ctypes.c_int),
    ("IsIconic", [_HWND], ctypes.c_int),
    ("IsZoomed", [_HWND], ctypes.c_int),
    ("IsHungAppWindow", [_HWND], ctypes.c_int),
    ("ShowWindow", [_HWND, ctypes.c_int], ctypes.c_int),
    ("ShowWindowAsync", [_HWND, ctypes.c_int], ctypes.c_int),
    ("GetForegroundWindow", [], _HWND),
    ("SetForegroundWindow", [_HWND], ctypes.c_int),
    ("GetWindowLongPtrW", [_HWND, ctypes.c_int], ctypes.c_ssize_t),
    ("SetWindowLongPtrW", [_HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t),
    ("AttachThreadInput", [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int], ctypes.c_int),
    (
        "GetWindowThreadProcessId",
        [_HWND, ctypes.POINTER(ctypes.c_ulong)],
        ctypes.c_ulong,
    ),
    ("GetWindow", [_HWND, ctypes.c_uint], _HWND),
    ("GetWindowTextLengthW", [_HWND], ctypes.c_int),
    ("GetWindowTextW", [_HWND, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
    ("GetClassNameW", [_HWND, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
    ("GetDlgCtrlID", [_HWND], ctypes.c_int),
    ("EnumWindows", [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
    ("EnumChildWindows", [_HWND, ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
    (
        "PostMessageW",
        [_HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t],
        ctypes.c_int,
    ),
    (
        "SendMessageTimeoutW",
        [
            _HWND,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_size_t),
        ],
        ctypes.c_ssize_t,
    ),
]


def load_user32(platform: str | None = None, loader: Any = None) -> Any | None:
    """Load ``user32`` with typed signatures, or ``None`` off Windows.

    Args:
        platform: ``sys.platform`` (tests pass another value).
        loader: ``ctypes.WinDLL`` (tests pass a fake).

    Returns:
        The DLL, or ``None`` where there is no ``user32``.
    """
    if (platform or sys.platform) != "win32":
        return None
    dll = (loader or ctypes.WinDLL)("user32", use_last_error=True)
    for name, argtypes, restype in _SIGNATURES:
        function = getattr(dll, name)
        function.argtypes = argtypes
        function.restype = restype
    return dll


class SolidWorksWindow:
    """The connected SolidWorks' main frame window.

    Attributes:
        hwnd: The frame's window handle (``IFrame.GetHWnd``).
    """

    def __init__(self, hwnd: int, user32: Any | None = None) -> None:
        """Bind to a window.

        Args:
            hwnd: The frame's window handle.
            user32: A ``user32``-like object; loaded from Windows when omitted.
        """
        self.hwnd = int(hwnd)
        self._user32 = user32 if user32 is not None else load_user32()

    @property
    def available(self) -> bool:
        """Whether the handle names a live window this process can see."""
        return bool(self.hwnd and self._user32 and self._user32.IsWindow(self.hwnd))

    def state(self) -> str:
        """The window's state, one of :data:`WINDOW_STATES`."""
        if not self.available:
            return "unknown"
        user32 = self._user32
        if not user32.IsWindowVisible(self.hwnd):
            return "hidden"
        if user32.IsIconic(self.hwnd):
            return "minimized"
        if user32.IsZoomed(self.hwnd):
            return "maximized"
        return "normal"

    def is_minimized(self) -> bool:
        """Whether the window is minimized."""
        return self.state() == "minimized"

    def has_modal_dialog(self) -> bool:
        """Whether SolidWorks shows a modal dialog (its frame is disabled)."""
        return self.available and not self._user32.IsWindowEnabled(self.hwnd)

    def is_responding(self, timeout_ms: int = 1000) -> bool:
        """Whether SolidWorks' UI thread answers a message within ``timeout_ms``.

        A SolidWorks busy in a long call (its own, or another program's) does
        not process messages, so it doesn't answer; one showing a dialog
        does. Windows' own "not responding" flag (``IsHungAppWindow``, set
        after 5 s without messages) answers first, without waiting. A window
        that can't be found counts as responding: there is nothing to wait
        for, and the call itself will say what is wrong.
        """
        if not self.available:
            return True
        if self._user32.IsHungAppWindow(self.hwnd):
            return False
        result = ctypes.c_size_t(0)
        return bool(
            self._user32.SendMessageTimeoutW(
                self.hwnd,
                WM_NULL,
                0,
                0,
                SMTO_BLOCK | SMTO_ABORTIFHUNG,
                int(timeout_ms),
                ctypes.byref(result),
            )
        )

    def show_without_focus(self) -> None:
        """Restore the window without activating it (``ShowWindowAsync``).

        A minimized window hides the dialogs it owns, so a modal dialog
        SolidWorks opens while minimized can't be seen, cancelled by the
        watchdog, or answered by the user until the window is shown.
        """
        if self.available:
            self._user32.ShowWindowAsync(self.hwnd, SW_SHOWNOACTIVATE)

    def process_id(self, hwnd: int | None = None) -> int:
        """The id of the process that owns ``hwnd`` (default: this window)."""
        if not self._user32:
            return 0
        pid = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(
            self.hwnd if hwnd is None else hwnd, ctypes.pointer(pid)
        )
        return int(pid.value)

    def foreground_window(self) -> int:
        """The foreground window's handle (``0`` when there is none)."""
        if not self._user32:
            return 0
        return int(self._user32.GetForegroundWindow() or 0)

    def foreground_is_solidworks(self) -> bool:
        """Whether the foreground window (or one of its dialogs) is SolidWorks'."""
        if not self.available:
            return False
        foreground = self.foreground_window()
        if not foreground:
            return False
        return self.process_id(foreground) == self.process_id()

    def minimize(self, wait: bool = True, focus_to: int = 0) -> bool:
        """Minimize without leaving SolidWorks in the foreground.

        With ``focus_to`` (the window the user was in), SolidWorks is
        minimized without activating anything (``SW_SHOWMINNOACTIVE``) and the
        focus goes straight to that window. ``SW_MINIMIZE`` lets Windows pick
        the next window in the Z-order, which was sometimes the desktop
        ("Program Manager"), a switch a window manager acts on (live check
        3). Without ``focus_to``, ``SW_MINIMIZE`` is the fallback when
        SolidWorks has the foreground.

        Args:
            wait: ``False`` uses ``ShowWindowAsync``, which doesn't wait for
                a busy SolidWorks to process it (the keeper's thread uses it
                while a call is running).
            focus_to: The window to give the focus to; ``0`` for none.

        Returns:
            Whether the window is minimized afterwards (``True`` when not
            waiting).
        """
        if not self.available:
            return False
        solidworks_has_focus = self.foreground_is_solidworks()
        hand_over = bool(focus_to) and solidworks_has_focus
        command = (
            SW_MINIMIZE
            if solidworks_has_focus and not hand_over
            else SW_SHOWMINNOACTIVE
        )
        show = self._user32.ShowWindow if wait else self._user32.ShowWindowAsync
        show(self.hwnd, command)
        if hand_over:
            self.give_focus_to(focus_to)
        return self.is_minimized() if wait else True

    def restore(self) -> bool:
        """Restore the window for the user to see.

        Returns:
            Whether the window is no longer minimized.
        """
        if not self.available:
            return False
        self._user32.ShowWindow(self.hwnd, SW_RESTORE)
        return self.state() in ("normal", "maximized")

    def give_focus_to(self, hwnd: int) -> bool:
        """Make ``hwnd`` the foreground window again, taking it from SolidWorks.

        Windows lets a process change the foreground window only when it owns
        the foreground or shares its input queue, so this briefly attaches to
        the foreground window's thread (``AttachThreadInput``) around
        ``SetForegroundWindow``.

        Args:
            hwnd: The window that had the focus before SolidWorks took it.

        Returns:
            Whether ``hwnd`` is the foreground window afterwards.
        """
        user32 = self._user32
        if not hwnd or not user32 or not user32.IsWindow(hwnd):
            return False
        foreground = self.foreground_window()
        foreground_thread = (
            int(user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
        )
        own_thread = threading.get_native_id()
        attached = bool(
            foreground_thread
            and foreground_thread != own_thread
            and user32.AttachThreadInput(own_thread, foreground_thread, True)
        )
        try:
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(own_thread, foreground_thread, False)
        return self.foreground_window() == int(hwnd)

    def _ex_style(self) -> int:
        return int(self._user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE))

    def block_activation(self) -> bool:
        """Stop SolidWorks' frame from being activated (``WS_EX_NOACTIVATE``).

        ``NewDocument`` makes SolidWorks bring its frame to the front for
        50-150 ms even while minimized, which window managers listening to
        ``EVENT_SYSTEM_FOREGROUND`` (the user's Stage Manager) act on. With
        ``WS_EX_NOACTIVATE`` on the frame it never became the foreground
        window (live probe, 2026-11-10: 0 of 2 part creations against 6 of 6
        without). ``LockSetForegroundWindow`` didn't help (6 of 6 with it).

        Undo it with :meth:`allow_activation` as soon as the call is over:
        while it is set the user can't bring SolidWorks up by clicking it.

        Returns:
            Whether the style was added here (``False`` when it was already
            set, or there is no window).
        """
        if not self.available:
            return False
        style = self._ex_style()
        if style & WS_EX_NOACTIVATE:
            return False
        self._user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        return True

    def allow_activation(self) -> None:
        """Remove ``WS_EX_NOACTIVATE`` again (also a leftover from a crashed server)."""
        if not self.available:
            return
        style = self._ex_style()
        if style & WS_EX_NOACTIVATE:
            self._user32.SetWindowLongPtrW(
                self.hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE
            )

    def give_focus_back(
        self,
        hwnd: int,
        attempts: int = 10,
        interval: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> bool:
        """Keep trying :meth:`give_focus_to` while SolidWorks has the focus.

        Right after a document opens SolidWorks is busy with its own UI work
        and a first attempt can fail; a few tries a tenth of a second apart
        get through (measured on SW 2026 SP4.1).

        Returns:
            Whether SolidWorks no longer has the focus.
        """
        for _ in range(attempts):
            if not self.foreground_is_solidworks() or self.give_focus_to(hwnd):
                return True
            sleep(interval)
        return not self.foreground_is_solidworks()

    def give_focus_back_soon(self, hwnd: int) -> threading.Thread:
        """Run :meth:`give_focus_back` on a background thread (Win32 only)."""
        thread = threading.Thread(
            target=self.give_focus_back,
            args=(hwnd,),
            name="solidworks-focus-return",
            daemon=True,
        )
        thread.start()
        return thread


class MinimizeKeeper:
    """Keeps SolidWorks minimized while the user wants it so, from its own thread.

    Checking only around the adapter's own operations wasn't enough: anything
    that restored SolidWorks between them (a COM call that doesn't go through
    ``_handle_com_operation``, a second adapter) left it up for good, because
    the next operation saw a visible window and took it for one the user had
    restored (live regression run, 2026-11-10).

    So the wish is remembered (:meth:`want`) and a thread looks at the window
    every :attr:`poll_seconds`. When SolidWorks comes up:

    * while an operation runs, or within :attr:`grace_seconds` of any COM
      activity (:meth:`activity`), SolidWorks did it: it is minimized again
      at once (``ShowWindowAsync``, so a busy SolidWorks doesn't block the
      thread) and the focus goes back to the user's last window;
    * otherwise the user restored it: the wish is dropped and it stays up.

    One keeper per window per process (:func:`keeper_for`), so every adapter
    talking to the same SolidWorks shares it. Win32 calls only, no COM.
    """

    def __init__(
        self,
        window: SolidWorksWindow,
        *,
        poll_seconds: float = 0.15,
        grace_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Watch one window (the thread starts with :meth:`want`)."""
        self.window = window
        self.poll_seconds = poll_seconds
        self.grace_seconds = grace_seconds
        self._clock = clock
        self.wanted = False
        self.user_focus = 0
        #: How many times SolidWorks came up and was minimized again.
        self.restores_undone = 0
        self._depth = 0
        self._last_activity = float("-inf")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        """Whether SolidWorks is being driven now, or was a moment ago."""
        return self._depth > 0 or (
            self._clock() - self._last_activity < self.grace_seconds
        )

    def activity(self) -> None:
        """Record a COM call (any, guarded or not)."""
        self._last_activity = self._clock()

    def begin(self) -> None:
        """An operation starts."""
        with self._lock:
            self._depth += 1
        self.activity()

    def end(self) -> None:
        """An operation ended."""
        with self._lock:
            self._depth = max(0, self._depth - 1)
        self.activity()

    def want(self, minimized: bool) -> None:
        """Remember whether the user wants SolidWorks minimized."""
        self.wanted = minimized
        if minimized:
            self._start()

    def _start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="solidworks-minimize-keeper", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread (tests; the server's keeper lives with the process)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while self.wanted and not self._stop.wait(self.poll_seconds):
            self.check()

    def check(self) -> None:
        """Look once and act (what the thread runs; tests call it directly)."""
        window = self.window
        if not self.wanted or not window.available:
            return
        solidworks_has_focus = window.foreground_is_solidworks()
        if not solidworks_has_focus:
            self.user_focus = window.foreground_window() or self.user_focus
        # A modal dialog is up: the window must stay shown, or the dialog is
        # hidden with it and the watchdog can't see or cancel it (it blocked a
        # call for 221 s in the live test, 2026-11-10).
        modal = window.has_modal_dialog()
        if window.is_minimized():
            if modal and self.busy:
                window.show_without_focus()
            elif solidworks_has_focus and self.user_focus:
                window.give_focus_to(self.user_focus)
            return
        if modal:
            return
        if self.busy:
            window.minimize(wait=False, focus_to=self.user_focus)
            self.restores_undone += 1
        else:
            self.wanted = False  # the user restored it


_KEEPERS: dict[int, MinimizeKeeper] = {}
_KEEPERS_LOCK = threading.Lock()


def keeper_for(window: SolidWorksWindow) -> MinimizeKeeper:
    """The process's keeper for ``window`` (created on first use)."""
    with _KEEPERS_LOCK:
        keeper = _KEEPERS.get(window.hwnd)
        if keeper is None:
            keeper = _KEEPERS[window.hwnd] = MinimizeKeeper(window)
        return keeper


def drop_keeper(window: SolidWorksWindow) -> None:
    """Stop and forget the keeper of a window that has gone.

    Called when the SolidWorks that owned it exited; a window it no longer
    has can't be kept minimized.
    """
    with _KEEPERS_LOCK:
        keeper = _KEEPERS.pop(window.hwnd, None)
    if keeper is not None:
        keeper.wanted = False
        keeper.stop()
