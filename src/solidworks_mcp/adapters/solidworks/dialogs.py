"""Find, describe and cancel SolidWorks' modal dialogs, through Win32 only.

A modal dialog SolidWorks opens during a COM call (a "Save Modified
Documents" prompt, a "Cannot open" error) blocks that call, and with it the
server's only COM thread, until someone answers it (pitfall #32 and the macro
section of ``docs/agents/com-api-pitfalls.md``). :class:`DialogWatchdog`
watches for such dialogs from a separate thread while an operation runs.
After a timeout it records the dialog's text and cancels it, so the COM call
returns and the agent gets the text instead of a hang.

The watchdog only ever cancels: it posts ``IDCANCEL`` (the Cancel button, or
Esc), then ``WM_CLOSE``. It never presses Save, Don't Save, Yes or No. A dialog
it can't cancel is handed to ``on_unanswerable`` (the adapter restores the
SolidWorks window so the user can answer it).

Like ``window.py`` it makes no COM calls, so it may run on any thread.
"""

from __future__ import annotations

import ctypes
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .window import SolidWorksWindow

WM_CLOSE = 0x0010
WM_GETTEXT = 0x000D
WM_COMMAND = 0x0111
SMTO_ABORTIFHUNG = 0x0002
#: How long reading one control's text may take before it is skipped.
GETTEXT_TIMEOUT_MS = 200
_TEXT_BUFFER = 2048
TDM_CLICK_BUTTON = 0x0400 + 102
IDCANCEL = 2
GW_OWNER = 4

DIALOG_CLASS = "#32770"
#: A dialog with a progress bar is SolidWorks working, not asking.
PROGRESS_CLASS = "msctls_progress32"
#: Task dialogs draw their content in one of these instead of child controls.
TASK_DIALOG_CLASS = "DirectUIHWND"

#: SolidWorks message boxes that close themselves say so in their title, e.g.
#: "SOLIDWORKS Design 2026 (Automatically dismissing in 5 seconds)".
_SELF_DISMISSING = re.compile(r"dismissing in (\d+) second", re.IGNORECASE)
#: Extra seconds a self-dismissing dialog gets past its own countdown.
SELF_DISMISS_GRACE_SECONDS = 2.0
#: The longest a self-dismissing dialog is left alone, in case its countdown
#: stalls; after that it is cancelled like any other.
SELF_DISMISS_MAX_SECONDS = 30.0

_ENUM_PROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
)


@dataclass
class DialogInfo:
    """What a dialog said, and what the watchdog did about it."""

    hwnd: int
    title: str
    texts: list[str] = field(default_factory=list)
    buttons: list[str] = field(default_factory=list)
    task_dialog: bool = False
    #: The messages posted, in order: ``cancel``, then ``close``.
    actions: list[str] = field(default_factory=list)
    #: Whether the dialog had gone when last checked.
    closed: bool = False
    #: Whether neither message closed it and it was handed to the user.
    handed_to_user: bool = False

    def to_dict(self) -> dict[str, Any]:
        """The dialog as plain data, without the window handle."""
        data = asdict(self)
        data.pop("hwnd")
        return data

    def summary(self) -> str:
        """One line for an error message."""
        text = " ".join(t for t in self.texts if t)
        head = f"'{self.title}'" if self.title else "a dialog"
        return f"{head}: {text}" if text else head


def _text(user32: Any, hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return str(buffer.value)


def _control_text(user32: Any, hwnd: int) -> str:
    """A control's text, read with ``WM_GETTEXT`` when it isn't its caption.

    ``GetWindowText`` only returns another process's window *caption*; edit
    and rich-edit controls keep their text themselves and answer only
    ``WM_GETTEXT``. That is sent with a timeout, so a hung SolidWorks can't
    hang the watchdog.
    """
    if text := _text(user32, hwnd):
        return text
    buffer = ctypes.create_unicode_buffer(_TEXT_BUFFER)
    result = ctypes.c_size_t(0)
    sent = user32.SendMessageTimeoutW(
        hwnd,
        WM_GETTEXT,
        _TEXT_BUFFER,
        ctypes.addressof(buffer),
        SMTO_ABORTIFHUNG,
        GETTEXT_TIMEOUT_MS,
        ctypes.pointer(result),
    )
    return str(buffer.value) if sent else ""


def _class_name(user32: Any, hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return str(buffer.value)


def _enum(enumerate_windows: Callable[[Any], Any]) -> list[int]:
    found: list[int] = []

    def collect(hwnd: Any, _lparam: Any) -> int:
        if hwnd:
            found.append(int(hwnd))
        return 1

    enumerate_windows(_ENUM_PROC(collect))
    return found


def top_level_windows(user32: Any) -> list[int]:
    """Every top-level window on the desktop."""
    return _enum(lambda callback: user32.EnumWindows(callback, None))


def child_windows(user32: Any, hwnd: int) -> list[int]:
    """Every descendant window of ``hwnd``."""
    return _enum(lambda callback: user32.EnumChildWindows(hwnd, callback, None))


def find_modal_dialogs(window: SolidWorksWindow, user32: Any) -> list[int]:
    """The modal dialogs SolidWorks is showing.

    A dialog counts when it belongs to SolidWorks' process, is a visible,
    enabled ``#32770`` window, has no progress bar, and SolidWorks' frame is
    disabled (which is what a modal dialog does to its owner).

    Args:
        window: The connected SolidWorks' frame.
        user32: The ``user32`` to use.

    Returns:
        The dialogs' window handles; empty when the frame is enabled.
    """
    if not window.available or user32.IsWindowEnabled(window.hwnd):
        return []
    pid = window.process_id()
    dialogs = []
    for hwnd in top_level_windows(user32):
        if hwnd == window.hwnd or window.process_id(hwnd) != pid:
            continue
        if not user32.IsWindowVisible(hwnd) or not user32.IsWindowEnabled(hwnd):
            continue
        if _class_name(user32, hwnd) != DIALOG_CLASS:
            continue
        children = [_class_name(user32, c) for c in child_windows(user32, hwnd)]
        if PROGRESS_CLASS in children:
            continue
        dialogs.append(hwnd)
    return dialogs


def describe_dialog(user32: Any, hwnd: int) -> DialogInfo:
    """Read a dialog's title, and its visible static texts and button captions.

    Hidden controls are skipped: SolidWorks' message boxes carry every
    possible button (OK, Cancel, Yes, No, Abort, ...) and show only some.
    """
    info = DialogInfo(hwnd=hwnd, title=_text(user32, hwnd))
    for child in child_windows(user32, hwnd):
        kind = _class_name(user32, child)
        if kind == TASK_DIALOG_CLASS:
            info.task_dialog = True
        elif not user32.IsWindowVisible(child):
            continue
        elif kind == "Button":
            if caption := _text(user32, child).replace("&", "").strip():
                info.buttons.append(caption)
        elif text := _control_text(user32, child).strip():
            info.texts.append(text)
    return info


def patience_for(title: str, timeout: float, elapsed: float = 0.0) -> float:
    """Seconds, from when it appeared, to leave a dialog alone before cancelling it.

    A SolidWorks message box that dismisses itself (for example "Models
    contained within the assembly have changed. Would you like to rebuild the
    assembly now?") gets the rest of its countdown plus
    :data:`SELF_DISMISS_GRACE_SECONDS`, so it closes the way SolidWorks
    intends instead of being cancelled first; at most
    :data:`SELF_DISMISS_MAX_SECONDS`. SolidWorks adds the countdown to the
    title after the box appears and updates it every second, so the watchdog
    asks again on every poll.

    Args:
        title: The dialog's title now.
        timeout: The watchdog's timeout.
        elapsed: Seconds since the dialog appeared.
    """
    match = _SELF_DISMISSING.search(title)
    if match:
        remaining = elapsed + int(match.group(1)) + SELF_DISMISS_GRACE_SECONDS
        return min(max(timeout, remaining), SELF_DISMISS_MAX_SECONDS)
    return timeout


def _cancel_button(user32: Any, hwnd: int) -> tuple[int, int]:
    """``(control id, handle)`` of the dialog's visible Cancel button.

    ``(IDCANCEL, 0)`` without one: a dialog treats that like Esc.
    """
    for child in child_windows(user32, hwnd):
        if _class_name(user32, child) != "Button" or not user32.IsWindowVisible(child):
            continue
        control_id = user32.GetDlgCtrlID(child)
        caption = _text(user32, child).replace("&", "").strip().lower()
        if control_id == IDCANCEL or caption == "cancel":
            return control_id, child
    return IDCANCEL, 0


def post_cancel(user32: Any, info: DialogInfo) -> None:
    """Ask the dialog to cancel, the way its Cancel button (or Esc) would.

    ``WM_COMMAND`` works on a dialog that isn't active, where ``BM_CLICK``
    may not. Task dialogs take ``TDM_CLICK_BUTTON`` instead.
    """
    if info.task_dialog:
        user32.PostMessageW(info.hwnd, TDM_CLICK_BUTTON, IDCANCEL, 0)
    else:
        control_id, button = _cancel_button(user32, info.hwnd)
        user32.PostMessageW(info.hwnd, WM_COMMAND, control_id, button)
    info.actions.append("cancel")


def post_close(user32: Any, info: DialogInfo) -> None:
    """Ask the dialog to close, like its title-bar X."""
    user32.PostMessageW(info.hwnd, WM_CLOSE, 0, 0)
    info.actions.append("close")


@dataclass
class _Tracked:
    info: DialogInfo | None = None
    first_seen: float = 0.0
    #: Seconds to leave this dialog alone (see :func:`patience_for`).
    patience: float = 0.0
    last_action: float = 0.0
    gave_up: bool = False


class DialogWatchdog:
    """Cancels SolidWorks' modal dialogs that stay open during an operation.

    ``arm()`` before the operation starts a polling thread; ``disarm()`` after
    it stops the thread and returns the dialogs it handled. :meth:`check`
    does one poll and is what the thread calls (tests call it directly).
    """

    def __init__(
        self,
        window: SolidWorksWindow,
        timeout: float,
        *,
        user32: Any | None = None,
        poll_seconds: float = 0.25,
        retry_seconds: float = 1.5,
        clock: Callable[[], float] = time.monotonic,
        on_unanswerable: Callable[[DialogInfo], None] | None = None,
    ) -> None:
        """Watch one SolidWorks.

        Args:
            window: The connected SolidWorks' frame.
            timeout: Seconds a dialog may stay open before it is cancelled;
                ``0`` or less turns the watchdog off.
            user32: The ``user32`` to use; the window's by default.
            poll_seconds: How often the thread looks.
            retry_seconds: How long each message gets to close the dialog.
            clock: A monotonic clock (tests pass a fake).
            on_unanswerable: Called once for a dialog neither message closed.
        """
        self.window = window
        self.timeout = timeout
        self._user32 = user32 if user32 is not None else window._user32
        self._poll = poll_seconds
        self._retry = retry_seconds
        self._clock = clock
        self._on_unanswerable = on_unanswerable
        self._tracked: dict[int, _Tracked] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether this watchdog can act: a timeout and a live window."""
        return self.timeout > 0 and self.window.available

    def arm(self) -> None:
        """Start watching (a no-op when disabled or already armed)."""
        if not self.enabled or self._thread is not None:
            return
        self._tracked = {}
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="solidworks-dialog-watchdog", daemon=True
        )
        self._thread.start()

    def disarm(self) -> list[DialogInfo]:
        """Stop watching.

        Returns:
            The dialogs that were cancelled or closed while armed.
        """
        thread, self._thread = self._thread, None
        if thread is not None:
            self._stop.set()
            thread.join(timeout=2.0)
        with self._lock:
            handled = [t.info for t in self._tracked.values() if t.info is not None]
            self._tracked = {}
        if handled:
            # A dialog may have closed after the last poll.
            open_now = set(find_modal_dialogs(self.window, self._user32))
            for info in handled:
                info.closed = info.hwnd not in open_now
        return handled

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            self.check()

    def check(self) -> None:
        """Look once: start timing new dialogs, act on those past the timeout."""
        now = self._clock()
        open_now = set(find_modal_dialogs(self.window, self._user32))
        with self._lock:
            for hwnd, tracked in self._tracked.items():
                if tracked.info is not None and hwnd not in open_now:
                    tracked.info.closed = True
            for hwnd in open_now:
                tracked = self._tracked.setdefault(
                    hwnd, _Tracked(first_seen=now, patience=self.timeout)
                )
                title = _text(self._user32, hwnd)
                tracked.patience = max(
                    tracked.patience,
                    patience_for(title, self.timeout, now - tracked.first_seen),
                )
                self._act(hwnd, tracked, now)

    def _act(self, hwnd: int, tracked: _Tracked, now: float) -> None:
        if tracked.gave_up or now - tracked.first_seen < tracked.patience:
            return
        if tracked.info is None:
            tracked.info = describe_dialog(self._user32, hwnd)
        info = tracked.info
        info.closed = False
        if now - tracked.last_action < self._retry and info.actions:
            return
        if "cancel" not in info.actions:
            post_cancel(self._user32, info)
        elif "close" not in info.actions:
            post_close(self._user32, info)
        else:
            tracked.gave_up = True
            info.handed_to_user = True
            if self._on_unanswerable is not None:
                self._on_unanswerable(info)
            return
        tracked.last_action = now
