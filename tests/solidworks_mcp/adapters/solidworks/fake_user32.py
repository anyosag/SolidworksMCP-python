"""A fake ``user32`` for the window and dialog tests.

It keeps a small table of windows and implements the ``user32`` functions
``adapters/solidworks/window.py`` and ``dialogs.py`` call, with the same names
and argument shapes (ctypes pointers and unicode buffers included), so the
code under test runs unchanged without Windows.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SW_SHOWNOACTIVATE = 4
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_RESTORE = 9
GW_OWNER = 4


@dataclass
class FakeWindow:
    """One window in the fake desktop."""

    hwnd: int
    pid: int
    title: str = ""
    class_name: str = ""
    visible: bool = True
    iconic: bool = False
    zoomed: bool = False
    enabled: bool = True
    owner: int = 0
    parent: int = 0
    control_id: int = 0
    #: The window's thread; defaults to ``pid * 10``.
    thread: int = 0
    #: Text only ``WM_GETTEXT`` returns (an edit control's own text).
    message_text: str = ""
    #: A hung window: ``SendMessageTimeoutW`` times out.
    hung: bool = False
    #: ``GWL_EXSTYLE`` (``WS_EX_APPWINDOW`` by default, like a main frame).
    ex_style: int = 0x00040000
    children: list[int] = field(default_factory=list)


class FakeUser32:
    """Fake ``user32``: windows, foreground, focus rules, and a call log."""

    def __init__(self) -> None:
        self.windows: dict[int, FakeWindow] = {}
        self.foreground = 0
        #: Where focus goes when the foreground window is minimized.
        self.next_foreground = 0
        #: Like Windows: SetForegroundWindow only works while attached to the
        #: foreground thread. ``False`` lets it always work.
        self.foreground_needs_attach = True
        self.attached: set[tuple[int, int]] = set()
        self.attach_calls: list[tuple[int, int, bool]] = []
        #: SetWindowLongPtrW calls: (hwnd, index, value).
        self.style_calls: list[tuple[int, int, int]] = []
        self.show_calls: list[tuple[int, int]] = []
        self.messages: list[tuple[str, int, int, int, int]] = []
        #: Called as on_message(hwnd, msg, wparam, lparam) for each message.
        self.on_message: Callable[[int, int, int, int], None] | None = None

    def add(self, hwnd: int, pid: int, **fields: Any) -> FakeWindow:
        """Add a window; a ``parent`` also lists it as that window's child."""
        window = FakeWindow(hwnd, pid, **fields)
        window.thread = window.thread or pid * 10
        self.windows[hwnd] = window
        if window.parent:
            self.windows[window.parent].children.append(hwnd)
        return window

    def remove(self, hwnd: int) -> None:
        """Destroy a window and its children."""
        window = self.windows.pop(hwnd, None)
        if window is None:
            return
        for child in window.children:
            self.windows.pop(child, None)

    # -- state ---------------------------------------------------------
    def IsWindow(self, hwnd: int) -> int:  # noqa: N802 - Win32 name
        return int(hwnd in self.windows)

    def IsWindowVisible(self, hwnd: int) -> int:  # noqa: N802
        return int(self.windows[hwnd].visible)

    def IsWindowEnabled(self, hwnd: int) -> int:  # noqa: N802
        return int(self.windows[hwnd].enabled)

    def IsIconic(self, hwnd: int) -> int:  # noqa: N802
        return int(self.windows[hwnd].iconic)

    def IsZoomed(self, hwnd: int) -> int:  # noqa: N802
        return int(self.windows[hwnd].zoomed)

    def GetForegroundWindow(self) -> int:  # noqa: N802
        return self.foreground

    def GetWindowThreadProcessId(self, hwnd: int, pid_pointer: Any) -> int:  # noqa: N802
        window = self.windows.get(hwnd)
        if pid_pointer is not None:
            pid_pointer.contents.value = window.pid if window else 0
        return window.thread if window else 0

    # -- changes -------------------------------------------------------
    def ShowWindowAsync(self, hwnd: int, command: int) -> int:  # noqa: N802
        """Like ``ShowWindow`` (the fake has no message queue to wait on)."""
        return self.ShowWindow(hwnd, command)

    def ShowWindow(self, hwnd: int, command: int) -> int:  # noqa: N802
        self.show_calls.append((hwnd, command))
        window = self.windows[hwnd]
        if command in (SW_MINIMIZE, SW_SHOWMINNOACTIVE):
            if command == SW_MINIMIZE and self.foreground in self._family(hwnd):
                self.foreground = self.next_foreground
            window.iconic = True
        elif command in (SW_RESTORE, SW_SHOWNOACTIVATE):
            window.iconic = False
            window.visible = True
        return 1

    def AttachThreadInput(self, own: int, other: int, attach: bool) -> int:  # noqa: N802
        self.attach_calls.append((own, other, bool(attach)))
        if attach:
            self.attached.add((own, other))
        else:
            self.attached.discard((own, other))
        return 1

    def GetWindowLongPtrW(self, hwnd: int, index: int) -> int:  # noqa: N802
        """Only ``GWL_EXSTYLE`` (-20) is modelled."""
        return self.windows[hwnd].ex_style if index == -20 else 0

    def SetWindowLongPtrW(self, hwnd: int, index: int, value: int) -> int:  # noqa: N802
        self.style_calls.append((hwnd, index, value))
        window = self.windows[hwnd]
        previous = window.ex_style
        if index == -20:
            window.ex_style = value
        return previous

    def SetForegroundWindow(self, hwnd: int) -> int:  # noqa: N802
        current = self.windows.get(self.foreground)
        allowed = not self.foreground_needs_attach or any(
            current is not None and other == current.thread
            for _own, other in self.attached
        )
        if allowed:
            self.foreground = hwnd
        return int(allowed)

    # -- dialogs -------------------------------------------------------
    def GetWindow(self, hwnd: int, command: int) -> int:  # noqa: N802
        return self.windows[hwnd].owner if command == GW_OWNER else 0

    def GetWindowTextLengthW(self, hwnd: int) -> int:  # noqa: N802
        return len(self.windows[hwnd].title)

    def GetWindowTextW(self, hwnd: int, buffer: Any, size: int) -> int:  # noqa: N802
        buffer.value = self.windows[hwnd].title[: size - 1]
        return len(buffer.value)

    def GetClassNameW(self, hwnd: int, buffer: Any, size: int) -> int:  # noqa: N802
        buffer.value = self.windows[hwnd].class_name[: size - 1]
        return len(buffer.value)

    def GetDlgCtrlID(self, hwnd: int) -> int:  # noqa: N802
        return self.windows[hwnd].control_id

    def EnumWindows(self, callback: Any, lparam: Any) -> int:  # noqa: N802
        for hwnd in [h for h, w in self.windows.items() if not w.parent]:
            if not callback(hwnd, lparam):
                break
        return 1

    def EnumChildWindows(self, parent: int, callback: Any, lparam: Any) -> int:  # noqa: N802
        for hwnd in list(self.windows[parent].children):
            if not callback(hwnd, lparam):
                break
        return 1

    def PostMessageW(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:  # noqa: N802
        self.messages.append(("post", hwnd, msg, wparam, lparam))
        if self.on_message:
            self.on_message(hwnd, msg, wparam, lparam)
        return 1

    def SendMessageTimeoutW(  # noqa: N802
        self,
        hwnd: int,
        msg: int,
        wparam: int,
        lparam: int,
        flags: int,
        timeout: int,
        result: Any,
    ) -> int:
        """Answer ``WM_GETTEXT`` by writing ``message_text`` into the buffer."""
        window = self.windows[hwnd]
        if window.hung:
            return 0
        data = ctypes.create_unicode_buffer(window.message_text[: wparam - 1])
        ctypes.memmove(lparam, data, ctypes.sizeof(data))
        return 1

    def _family(self, hwnd: int) -> set[int]:
        """``hwnd`` plus every window of the same process."""
        pid = self.windows[hwnd].pid
        return {h for h, w in self.windows.items() if w.pid == pid}
