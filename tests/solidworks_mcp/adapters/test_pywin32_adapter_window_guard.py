"""Keeping a minimized SolidWorks minimized, and cancelling blocking dialogs.

``_handle_com_operation`` minimizes the window again after an operation that
restored it, gives the focus back, and turns a dialog the watchdog cancelled
into an error (the ``keep-solidworks-minimized`` OpenSpec change).
"""

from __future__ import annotations

import functools
import time
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import window as window_module
from solidworks_mcp.adapters.solidworks.dialogs import WM_COMMAND, DialogWatchdog
from solidworks_mcp.adapters.solidworks.window import (
    WS_EX_NOACTIVATE,
    MinimizeKeeper,
    SolidWorksWindow,
)

from .solidworks.fake_user32 import FakeUser32

SW_PID = 9396
FRAME = 0x1000
OTHER_APP = 0x2000
DIALOG = 0x3000


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> PyWin32Adapter:
    """A ``PyWin32Adapter`` that thinks it runs on Windows with pywin32."""
    monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(pywin32_adapter.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        pywin32_adapter, "pywintypes", SimpleNamespace(com_error=RuntimeError)
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS", "0")
    monkeypatch.delenv("SOLIDWORKS_MCP_KEEP_MINIMIZED", raising=False)
    monkeypatch.delenv("SOLIDWORKS_MCP_HEADLESS", raising=False)
    return PyWin32Adapter({})


@pytest.fixture
def user32() -> FakeUser32:
    """SolidWorks minimized, the user working in another app."""
    fake = FakeUser32()
    fake.add(FRAME, SW_PID, title="SOLIDWORKS", iconic=True)
    fake.add(OTHER_APP, 4242, title="Editor")
    fake.foreground = OTHER_APP
    # Like SW 2026: after it is minimized again it keeps the foreground.
    fake.next_foreground = FRAME
    return fake


@pytest.fixture
def attached(adapter: PyWin32Adapter, user32: FakeUser32) -> PyWin32Adapter:
    adapter._window = SolidWorksWindow(FRAME, user32)
    return adapter


@pytest.fixture(autouse=True)
def _fresh_keepers() -> Any:
    """Keepers are per process; don't let one leak into the next test."""
    yield
    for keeper in list(window_module._KEEPERS.values()):
        keeper.stop()
    window_module._KEEPERS.clear()


@pytest.fixture
def kept(attached: PyWin32Adapter) -> PyWin32Adapter:
    """``attached`` with a keeper whose thread isn't started (tests call check)."""
    assert attached._window is not None
    keeper = MinimizeKeeper(attached._window)
    keeper._start = lambda: None  # type: ignore[method-assign]
    attached._keeper = keeper
    return attached


class TestKeeper:
    def test_an_operation_on_a_minimized_window_remembers_the_wish(
        self, kept: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        kept._handle_com_operation("add_line", lambda: None)

        assert kept._keeper is not None and kept._keeper.wanted is True
        assert kept._keeper._depth == 0

    def test_a_restore_between_operations_is_undone_next_time(
        self, kept: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        """Something outside the guard restored it; the wish still holds."""
        kept._handle_com_operation("add_line", lambda: None)
        user32.windows[FRAME].iconic = False  # e.g. an unguarded COM call

        kept._handle_com_operation("add_circle", lambda: None)

        assert user32.windows[FRAME].iconic is True

    def test_attempt_counts_as_activity(self, kept: PyWin32Adapter) -> None:
        assert kept._keeper is not None
        kept._keeper.grace_seconds = 60
        assert kept._keeper.busy is False

        kept._attempt(lambda: None)

        assert kept._keeper.busy is True

    async def test_the_window_tool_sets_and_clears_the_wish(
        self, kept: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        assert kept._keeper is not None
        user32.windows[FRAME].iconic = False

        await kept.set_window_state("minimize")
        assert kept._keeper.wanted is True

        await kept.set_window_state("restore")
        assert kept._keeper.wanted is False

    def test_focus_remembered_by_the_keeper(self, kept: PyWin32Adapter) -> None:
        assert kept._keeper is not None
        kept._keeper.user_focus = OTHER_APP
        kept._window.foreground_is_solidworks = lambda: True  # type: ignore[method-assign,union-attr]

        assert kept._focus_to_return() == OTHER_APP

    def test_no_focus_to_return_without_a_window(self, adapter: PyWin32Adapter) -> None:
        assert adapter._window is None
        assert adapter._focus_to_return() == 0


def _restores(user32: FakeUser32) -> Any:
    """An operation that, like NewDocument, restores SolidWorks and takes focus."""

    def operation() -> str:
        user32.windows[FRAME].iconic = False
        user32.foreground = FRAME
        return "created"

    return operation


class TestKeepMinimizedWithoutKeeper:
    def test_a_restored_window_is_minimized_and_focus_returned(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        result = attached._handle_com_operation("create_part", _restores(user32))

        assert result.is_success and result.data == "created"
        assert user32.windows[FRAME].iconic is True
        assert user32.foreground == OTHER_APP

    def test_activation_is_blocked_during_the_operation(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        original = user32.windows[FRAME].ex_style
        states: list[bool] = []

        def operation() -> None:
            states.append(bool(user32.windows[FRAME].ex_style & WS_EX_NOACTIVATE))

        attached._handle_com_operation("create_part", operation)

        assert states == [True]
        assert user32.windows[FRAME].ex_style == original

    def test_activation_is_allowed_again_after_a_failure(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        def fails() -> None:
            raise ValueError("boom")

        attached._handle_com_operation("create_part", fails)

        assert not user32.windows[FRAME].ex_style & WS_EX_NOACTIVATE

    @pytest.mark.parametrize("case", ["visible", "setting_off", "solidworks_has_focus"])
    def test_activation_not_blocked(
        self,
        attached: PyWin32Adapter,
        user32: FakeUser32,
        monkeypatch: pytest.MonkeyPatch,
        case: str,
    ) -> None:
        if case == "visible":
            user32.windows[FRAME].iconic = False
        elif case == "setting_off":
            monkeypatch.setenv("SOLIDWORKS_MCP_BLOCK_ACTIVATION", "0")
        else:
            user32.foreground = FRAME

        attached._handle_com_operation("add_line", lambda: None)

        assert user32.style_calls == []

    def test_a_window_with_a_dialog_is_not_minimized(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        def opens_a_dialog() -> None:
            user32.windows[FRAME].iconic = False
            user32.windows[FRAME].enabled = False

        attached._handle_com_operation("execute_macro", opens_a_dialog)

        assert user32.windows[FRAME].iconic is False

    def test_a_window_the_user_restored_is_left_alone(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        user32.windows[FRAME].iconic = False

        attached._handle_com_operation("create_part", _restores(user32))

        assert user32.windows[FRAME].iconic is False
        assert user32.show_calls == []

    def test_turned_off(
        self,
        attached: PyWin32Adapter,
        user32: FakeUser32,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SOLIDWORKS_MCP_KEEP_MINIMIZED", "off")

        attached._handle_com_operation("create_part", _restores(user32))

        assert user32.windows[FRAME].iconic is False

    def test_no_focus_to_return_when_solidworks_had_it(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        user32.foreground = FRAME

        attached._handle_com_operation("create_part", _restores(user32))

        assert user32.windows[FRAME].iconic is True
        assert user32.attach_calls == []

    def test_focus_is_remembered_across_operations(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        """A tool runs several operations; the first one sees the user's window."""
        user32.AttachThreadInput = lambda *_args: 0  # type: ignore[method-assign]
        retries: list[int] = []
        attached._window.give_focus_back_soon = retries.append  # type: ignore[union-attr,method-assign]

        attached._handle_com_operation("create_part", _restores(user32))
        # The hand-back failed, so SolidWorks still has the focus...
        assert user32.foreground == FRAME
        assert retries == [OTHER_APP]  # ...and a background retry was started

        attached._handle_com_operation("set_units", lambda: None)

        assert retries == [OTHER_APP, OTHER_APP]

    def test_only_the_outermost_operation_acts(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        states: list[bool] = []

        def outer() -> str:
            attached._handle_com_operation("inner", _restores(user32))
            states.append(user32.windows[FRAME].iconic)
            return "done"

        attached._handle_com_operation("outer", outer)

        assert states == [False]  # the inner call did not minimize
        assert user32.windows[FRAME].iconic is True
        assert len(user32.show_calls) == 1
        assert attached._operation_depth == 0

    def test_without_a_window_nothing_changes(self, adapter: PyWin32Adapter) -> None:
        result = adapter._handle_com_operation("create_part", lambda: 1)

        assert result.is_success and result.data == 1


class TestDialogs:
    @pytest.fixture
    def quick(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS", "0.05")
        monkeypatch.setattr(
            pywin32_adapter,
            "DialogWatchdog",
            functools.partial(DialogWatchdog, poll_seconds=0.01, retry_seconds=0.05),
        )

    def _prompt(
        self, user32: FakeUser32, hwnd: int = DIALOG, closes: bool = True
    ) -> None:
        user32.add(hwnd, SW_PID, class_name="#32770", title="SOLIDWORKS", owner=FRAME)
        user32.add(
            hwnd + 1, SW_PID, class_name="Static", parent=hwnd, title="Save changes?"
        )
        user32.add(
            hwnd + 2,
            SW_PID,
            class_name="Button",
            parent=hwnd,
            title="Cancel",
            control_id=2,
        )
        user32.windows[FRAME].enabled = False

        def handle(target: int, msg: int, _wparam: int, _lparam: int) -> None:
            if closes and msg == WM_COMMAND:
                user32.remove(target)
                if not any(w.class_name == "#32770" for w in user32.windows.values()):
                    user32.windows[FRAME].enabled = True

        user32.on_message = handle

    def _blocked_until(self, condition: Any, then: Any = "saved") -> Any:
        """An operation that is stuck (like a COM call) until ``condition()``."""

        def operation() -> Any:
            deadline = time.monotonic() + 3
            while not condition() and time.monotonic() < deadline:
                time.sleep(0.005)
            if isinstance(then, Exception):
                raise then
            return then

        return operation

    def test_a_cancelled_dialog_becomes_an_error(
        self, attached: PyWin32Adapter, user32: FakeUser32, quick: None
    ) -> None:
        self._prompt(user32)

        result = attached._handle_com_operation(
            "save_file", self._blocked_until(lambda: DIALOG not in user32.windows)
        )

        assert result.is_error
        assert "SolidWorks showed a dialog during save_file" in result.error
        assert "'SOLIDWORKS': Save changes?" in result.error
        assert "cancelled it" in result.error
        assert result.data["dialog"]["buttons"] == ["Cancel"]
        assert result.data["dialog"]["actions"] == ["cancel"]
        assert "operation_error" not in result.data
        assert "dialogs" not in result.data

    def test_the_operation_error_is_kept(
        self, attached: PyWin32Adapter, user32: FakeUser32, quick: None
    ) -> None:
        self._prompt(user32)

        result = attached._handle_com_operation(
            "save_file",
            self._blocked_until(
                lambda: DIALOG not in user32.windows, ValueError("save failed")
            ),
        )

        assert result.data["operation_error"] == "Error in save_file: save failed"

    def test_several_dialogs(
        self, attached: PyWin32Adapter, user32: FakeUser32, quick: None
    ) -> None:
        self._prompt(user32, DIALOG)
        self._prompt(user32, DIALOG + 0x100)

        result = attached._handle_com_operation(
            "save_file",
            self._blocked_until(
                lambda: (
                    DIALOG not in user32.windows
                    and DIALOG + 0x100 not in user32.windows
                )
            ),
        )

        assert len(result.data["dialogs"]) == 2

    def test_a_dialog_that_wont_close_brings_solidworks_up(
        self, attached: PyWin32Adapter, user32: FakeUser32, quick: None
    ) -> None:
        self._prompt(user32, closes=False)
        user32.foreground = OTHER_APP

        def answered_by_the_user() -> bool:
            if user32.windows[FRAME].iconic:
                return False
            user32.remove(DIALOG)  # the user answers it...
            user32.windows[FRAME].enabled = True  # ...which re-enables the frame
            return True

        result = attached._handle_com_operation(
            "save_file", self._blocked_until(answered_by_the_user)
        )

        assert "could not cancel it, so SolidWorks was brought up" in result.error
        assert result.data["dialog"]["actions"] == ["cancel", "close"]
        assert result.data["dialog"]["handed_to_user"] is True
        # Minimized again once the operation is over.
        assert user32.windows[FRAME].iconic is True

    def test_a_dialog_still_open_when_the_operation_returns(
        self, attached: PyWin32Adapter, user32: FakeUser32, quick: None
    ) -> None:
        self._prompt(user32, closes=False)

        result = attached._handle_com_operation(
            "save_file", self._blocked_until(lambda: bool(user32.messages))
        )

        assert "asked it to cancel, but it was still open" in result.error

    def test_watchdog_off(self, attached: PyWin32Adapter, user32: FakeUser32) -> None:
        self._prompt(user32)

        result = attached._handle_com_operation("save_file", lambda: "saved")

        assert result.is_success
        assert user32.messages == []


class TestWindowTool:
    async def test_unknown_state(self, attached: PyWin32Adapter) -> None:
        result = await attached.set_window_state("maximize")

        assert result.is_error and "minimize or restore" in (result.error or "")

    async def test_without_a_window(self, adapter: PyWin32Adapter) -> None:
        result = await adapter.set_window_state("minimize")

        assert result.is_error and "not available" in (result.error or "")
        assert adapter._window_state() == "unknown"

    async def test_minimize_keeps_the_users_focus(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        user32.windows[FRAME].iconic = False

        result = await attached.set_window_state("minimize")

        assert result.data == {"window_state": "minimized"}
        assert user32.foreground == OTHER_APP

    async def test_minimize_gives_back_focus_solidworks_took(
        self, attached: PyWin32Adapter, user32: FakeUser32
    ) -> None:
        attached._user_focus = OTHER_APP  # remembered from an earlier call
        user32.windows[FRAME].iconic = False
        user32.foreground = FRAME

        await attached.set_window_state("minimize")

        assert user32.foreground == OTHER_APP

    async def test_restore(self, attached: PyWin32Adapter, user32: FakeUser32) -> None:
        result = await attached.set_window_state("restore")

        assert result.data == {"window_state": "normal"}


async def test_export_image_while_minimized_takes_no_focus(
    attached: PyWin32Adapter,
    user32: FakeUser32,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    from solidworks_mcp.adapters.solidworks import bitmap

    def save(_doc: Any, path: str, width: int, height: int) -> bool:
        bitmap.write_png(path, width, height, [b"\x80" * (3 * width)] * height)
        return True

    monkeypatch.setattr(attached, "_save_screenshot_sized", save)
    doc = SimpleNamespace(GetTitle=lambda: "part", GetPathName=lambda: "")
    focus = SimpleNamespace(SetFocus=lambda: pytest.fail("took the focus"))
    attached.currentModel = doc
    attached.swApp = SimpleNamespace(ActiveDoc=doc, Frame=focus, ActivateDoc3=None)

    result = await attached.export_image(
        {"file_path": str(tmp_path / "shot.png"), "width": 8, "height": 6}
    )

    assert result.is_success, result.error
    assert result.data["window_state"] == "minimized"
    assert result.data["dimensions"] == "8x6"


class _FakeFrame:
    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd

    def GetHWnd(self) -> int:  # noqa: N802 - COM name
        return self.hwnd


class TestConnect:
    @pytest.fixture
    def windows(
        self, monkeypatch: pytest.MonkeyPatch, user32: FakeUser32
    ) -> FakeUser32:
        monkeypatch.setattr(
            pywin32_adapter,
            "SolidWorksWindow",
            lambda hwnd: SolidWorksWindow(hwnd, user32),
        )
        return user32

    def test_attach_window_reads_the_frame_handle(
        self, adapter: PyWin32Adapter, windows: FakeUser32
    ) -> None:
        app = SimpleNamespace(Frame=lambda: _FakeFrame(FRAME))

        window = adapter._attach_window(app)

        assert window is adapter._window
        assert window is not None and window.hwnd == FRAME

    def test_attach_window_without_a_frame(
        self, adapter: PyWin32Adapter, windows: FakeUser32
    ) -> None:
        assert adapter._attach_window(SimpleNamespace()) is None
        assert adapter._window is None

    @pytest.mark.parametrize(
        ("state", "headless", "visible_after"),
        [
            ({"visible": False}, False, True),  # hidden: shown
            ({"iconic": True}, False, "untouched"),  # minimized: left alone
            ({}, False, "untouched"),  # visible: left alone
            ({}, True, False),  # headless: hidden
        ],
    )
    def test_show_window(
        self,
        windows: FakeUser32,
        monkeypatch: pytest.MonkeyPatch,
        state: dict,
        headless: bool,
        visible_after: object,
    ) -> None:
        if headless:
            monkeypatch.setenv("SOLIDWORKS_MCP_HEADLESS", "1")
        windows.windows[FRAME].iconic = False
        for name, value in state.items():
            setattr(windows.windows[FRAME], name, value)
        app = SimpleNamespace(Visible="untouched")

        pywin32_adapter._ComSessionCoordinator.show_window(
            app, SolidWorksWindow(FRAME, windows)
        )

        assert app.Visible == visible_after

    @pytest.mark.parametrize(("visible", "after"), [(False, True), (True, True)])
    def test_show_window_without_a_handle_reads_visible(
        self, visible: bool, after: bool
    ) -> None:
        app = SimpleNamespace(Visible=visible)

        pywin32_adapter._ComSessionCoordinator.show_window(app, None)

        assert app.Visible is after

    async def test_connect_keeps_a_minimized_window_minimized(
        self,
        adapter: PyWin32Adapter,
        windows: FakeUser32,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def restore_on_toggle(*_args: object) -> None:
            windows.windows[FRAME].iconic = False
            windows.foreground = FRAME

        app = SimpleNamespace(
            Frame=lambda: _FakeFrame(FRAME),
            Visible=True,
            SetUserPreferenceToggle=restore_on_toggle,
        )
        coordinator = adapter._session_coordinator
        monkeypatch.setattr(coordinator, "initialize_com_apartment", lambda: None)

        async def acquire() -> Any:
            return app

        monkeypatch.setattr(coordinator, "acquire_solidworks_application", acquire)
        windows.windows[FRAME].ex_style |= WS_EX_NOACTIVATE  # a crashed server's

        await adapter.connect()

        assert windows.windows[FRAME].iconic is True
        assert windows.foreground == OTHER_APP
        assert not windows.windows[FRAME].ex_style & WS_EX_NOACTIVATE

        monkeypatch.setattr(coordinator, "uninitialize_com_apartment", lambda: None)
        windows.windows[FRAME].ex_style |= WS_EX_NOACTIVATE
        await adapter.disconnect()
        assert adapter._window is None
        assert not windows.windows[FRAME].ex_style & WS_EX_NOACTIVATE
