"""Tests for finding, describing and cancelling SolidWorks' modal dialogs."""

from __future__ import annotations

import time

import pytest

from solidworks_mcp.adapters.solidworks.dialogs import (
    IDCANCEL,
    TDM_CLICK_BUTTON,
    WM_CLOSE,
    WM_COMMAND,
    DialogInfo,
    DialogWatchdog,
    describe_dialog,
    find_modal_dialogs,
    patience_for,
    post_cancel,
    post_close,
)
from solidworks_mcp.adapters.solidworks.window import SolidWorksWindow

from .fake_user32 import FakeUser32

SW_PID = 9396
FRAME = 0x1000
DIALOG = 0x3000


def _save_prompt(user32: FakeUser32, hwnd: int = DIALOG, **fields: object) -> None:
    """A 'Save Modified Documents' prompt with Save All / Don't Save / Cancel."""
    user32.add(
        hwnd, SW_PID, title="SOLIDWORKS", class_name="#32770", owner=FRAME, **fields
    )
    user32.add(
        hwnd + 1,
        SW_PID,
        class_name="Static",
        parent=hwnd,
        title="Save changes to Bracket.SLDPRT?",
    )
    user32.add(hwnd + 2, SW_PID, class_name="Static", parent=hwnd, title="  ")
    user32.add(
        hwnd + 3,
        SW_PID,
        class_name="Button",
        parent=hwnd,
        title="&Save All",
        control_id=6,
    )
    user32.add(
        hwnd + 4,
        SW_PID,
        class_name="Button",
        parent=hwnd,
        title="Do&n't Save",
        control_id=7,
    )
    user32.add(
        hwnd + 5,
        SW_PID,
        class_name="Button",
        parent=hwnd,
        title="Cancel",
        control_id=IDCANCEL,
    )
    user32.add(hwnd + 6, SW_PID, class_name="Button", parent=hwnd, title="")


@pytest.fixture
def user32() -> FakeUser32:
    fake = FakeUser32()
    fake.add(FRAME, SW_PID, title="SOLIDWORKS", enabled=False)
    return fake


@pytest.fixture
def window(user32: FakeUser32) -> SolidWorksWindow:
    return SolidWorksWindow(FRAME, user32)


def _closes_on(user32: FakeUser32, message: int) -> None:
    """Make dialogs disappear (and the frame re-enable) on ``message``."""

    def handle(hwnd: int, msg: int, wparam: int, lparam: int) -> None:
        if msg == message:
            user32.remove(hwnd)
            user32.windows[FRAME].enabled = True

    user32.on_message = handle


def test_dialog_info_as_data_and_text() -> None:
    info = DialogInfo(hwnd=1, title="SOLIDWORKS", texts=["Save changes?", ""])

    assert "hwnd" not in info.to_dict()
    assert info.to_dict()["title"] == "SOLIDWORKS"
    assert info.summary() == "'SOLIDWORKS': Save changes?"
    assert DialogInfo(hwnd=1, title="").summary() == "a dialog"
    assert DialogInfo(hwnd=1, title="Oops").summary() == "'Oops'"


def test_no_dialog_while_the_frame_is_enabled(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    _save_prompt(user32)
    user32.windows[FRAME].enabled = True

    assert find_modal_dialogs(window, user32) == []


def test_no_dialog_without_a_window(user32: FakeUser32) -> None:
    assert find_modal_dialogs(SolidWorksWindow(0, user32), user32) == []


def test_finds_only_solidworks_prompts(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    _save_prompt(user32)
    user32.add(0x4000, 1234, class_name="#32770", title="another app's dialog")
    user32.add(0x4100, SW_PID, class_name="#32770", visible=False)
    user32.add(0x4200, SW_PID, class_name="#32770", enabled=False)
    user32.add(0x4300, SW_PID, class_name="tooltips_class32")
    user32.add(0x4400, SW_PID, class_name="#32770", title="Opening")
    user32.add(0x4401, SW_PID, class_name="msctls_progress32", parent=0x4400)

    assert find_modal_dialogs(window, user32) == [DIALOG]


def test_describe_dialog(user32: FakeUser32) -> None:
    _save_prompt(user32)

    info = describe_dialog(user32, DIALOG)

    assert info.title == "SOLIDWORKS"
    assert info.texts == ["Save changes to Bracket.SLDPRT?"]
    assert info.buttons == ["Save All", "Don't Save", "Cancel"]
    assert info.task_dialog is False


def test_describe_skips_hidden_template_buttons(user32: FakeUser32) -> None:
    """SolidWorks' message boxes carry every button and show only some."""
    user32.add(DIALOG, SW_PID, class_name="#32770", title="SOLIDWORKS")
    for offset, caption in enumerate(["OK", "Cancel", "Yes", "No", "Abort"], start=1):
        user32.add(
            DIALOG + offset,
            SW_PID,
            class_name="Button",
            parent=DIALOG,
            title=caption,
            control_id=offset,
            visible=caption in ("Yes", "No"),
        )
    user32.add(
        DIALOG + 9, SW_PID, class_name="Static", parent=DIALOG, title="x", visible=False
    )

    info = describe_dialog(user32, DIALOG)
    post_cancel(user32, info)

    assert info.buttons == ["Yes", "No"]
    assert info.texts == []
    # The hidden Cancel button is not used: IDCANCEL works like Esc.
    assert user32.messages == [("post", DIALOG, WM_COMMAND, IDCANCEL, 0)]


def test_describe_reads_edit_controls_with_wm_gettext(user32: FakeUser32) -> None:
    """Another process's edit control text isn't its caption."""
    user32.add(DIALOG, SW_PID, class_name="#32770", title="SOLIDWORKS Design")
    user32.add(
        DIALOG + 1,
        SW_PID,
        class_name="RICHEDIT50W",
        parent=DIALOG,
        message_text="Save the modified documents?",
    )
    user32.add(
        DIALOG + 2,
        SW_PID,
        class_name="RICHEDIT50W",
        parent=DIALOG,
        message_text="unreadable",
        hung=True,
    )

    info = describe_dialog(user32, DIALOG)

    assert info.texts == ["Save the modified documents?"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("SOLIDWORKS Design 2026 (Automatically dismissing in 5 seconds)", 7.0),
        ("SOLIDWORKS (automatically dismissing in 1 second)", 5.0),
        ("SOLIDWORKS Design", 5.0),
    ],
)
def test_patience_for_self_dismissing_dialogs(title: str, expected: float) -> None:
    assert patience_for(title, 5.0) == expected


def test_patience_counts_from_when_the_dialog_appeared() -> None:
    title = "SOLIDWORKS (Automatically dismissing in 3 seconds)"

    assert patience_for(title, 5.0, elapsed=4.0) == 9.0
    assert patience_for(title, 5.0, elapsed=40.0) == 30.0  # a stalled countdown


def test_watchdog_waits_for_a_countdown_added_after_the_dialog_appeared(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    """SolidWorks adds "(Automatically dismissing in N seconds)" a moment later."""
    dialog = user32.add(
        DIALOG, SW_PID, class_name="#32770", title="SOLIDWORKS Design 2026"
    )
    clock = _Clock()
    watchdog = DialogWatchdog(window, 5, clock=clock)

    watchdog.check()
    clock.now += 1.0
    dialog.title = "SOLIDWORKS Design 2026 (Automatically dismissing in 4 seconds)"
    watchdog.check()
    clock.now += 5.0  # 6 s in: past the timeout, inside the countdown
    dialog.title = "SOLIDWORKS Design 2026 (Automatically dismissing in 1 seconds)"
    watchdog.check()
    assert user32.messages == []

    user32.remove(DIALOG)  # SolidWorks dismissed it
    user32.windows[FRAME].enabled = True
    clock.now += 1.0
    watchdog.check()
    assert watchdog.disarm() == []


def test_watchdog_cancels_a_stalled_countdown(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    user32.add(
        DIALOG,
        SW_PID,
        class_name="#32770",
        title="SOLIDWORKS (Automatically dismissing in 5 seconds)",
    )
    clock = _Clock()
    watchdog = DialogWatchdog(window, 5, clock=clock)

    for _ in range(29):
        watchdog.check()
        clock.now += 1.0
    assert user32.messages == []

    clock.now += 1.5
    watchdog.check()
    assert [m[2] for m in user32.messages] == [WM_COMMAND]


def test_watchdog_lets_a_self_dismissing_dialog_close_itself(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    user32.add(
        DIALOG,
        SW_PID,
        class_name="#32770",
        title="SOLIDWORKS Design 2026 (Automatically dismissing in 5 seconds)",
    )
    clock = _Clock()
    watchdog = DialogWatchdog(window, 5, clock=clock)

    watchdog.check()
    clock.now += 6.0
    watchdog.check()
    assert user32.messages == []  # within its own countdown + grace

    user32.remove(DIALOG)  # SolidWorks dismissed it
    user32.windows[FRAME].enabled = True
    clock.now += 1.0
    watchdog.check()

    assert watchdog.disarm() == []


def test_describe_task_dialog(user32: FakeUser32) -> None:
    user32.add(DIALOG, SW_PID, class_name="#32770", owner=FRAME)
    user32.add(DIALOG + 1, SW_PID, class_name="DirectUIHWND", parent=DIALOG)

    info = describe_dialog(user32, DIALOG)

    assert info.task_dialog is True
    assert info.title == ""


def test_cancel_uses_the_cancel_button(user32: FakeUser32) -> None:
    _save_prompt(user32)
    info = describe_dialog(user32, DIALOG)

    post_cancel(user32, info)

    assert user32.messages == [("post", DIALOG, WM_COMMAND, IDCANCEL, DIALOG + 5)]
    assert info.actions == ["cancel"]


def test_cancel_finds_a_cancel_caption_with_another_id(user32: FakeUser32) -> None:
    user32.add(DIALOG, SW_PID, class_name="#32770")
    user32.add(DIALOG + 1, SW_PID, class_name="Static", parent=DIALOG, title="Cancel")
    user32.add(
        DIALOG + 2, SW_PID, class_name="Button", parent=DIALOG, title="OK", control_id=1
    )
    user32.add(
        DIALOG + 3,
        SW_PID,
        class_name="Button",
        parent=DIALOG,
        title="&Cancel",
        control_id=1002,
    )

    post_cancel(user32, describe_dialog(user32, DIALOG))

    assert user32.messages == [("post", DIALOG, WM_COMMAND, 1002, DIALOG + 3)]


def test_cancel_without_a_cancel_button_sends_idcancel(user32: FakeUser32) -> None:
    user32.add(DIALOG, SW_PID, class_name="#32770")
    user32.add(
        DIALOG + 1, SW_PID, class_name="Button", parent=DIALOG, title="OK", control_id=1
    )

    post_cancel(user32, describe_dialog(user32, DIALOG))

    assert user32.messages == [("post", DIALOG, WM_COMMAND, IDCANCEL, 0)]


def test_cancel_a_task_dialog(user32: FakeUser32) -> None:
    user32.add(DIALOG, SW_PID, class_name="#32770")
    user32.add(DIALOG + 1, SW_PID, class_name="DirectUIHWND", parent=DIALOG)

    post_cancel(user32, describe_dialog(user32, DIALOG))

    assert user32.messages == [("post", DIALOG, TDM_CLICK_BUTTON, IDCANCEL, 0)]


def test_close(user32: FakeUser32) -> None:
    info = DialogInfo(hwnd=DIALOG, title="")

    post_close(user32, info)

    assert user32.messages == [("post", DIALOG, WM_CLOSE, 0, 0)]
    assert info.actions == ["close"]


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_watchdog_is_off_without_a_timeout_or_window(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    assert DialogWatchdog(window, 0).enabled is False
    assert DialogWatchdog(SolidWorksWindow(0, user32), 5).enabled is False

    watchdog = DialogWatchdog(window, 0)
    watchdog.arm()
    assert watchdog._thread is None
    assert watchdog.disarm() == []


def test_watchdog_waits_for_the_timeout_then_cancels(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    _save_prompt(user32)
    _closes_on(user32, WM_COMMAND)
    clock = _Clock()
    watchdog = DialogWatchdog(window, 5, clock=clock)

    watchdog.check()
    clock.now += 4.9
    watchdog.check()
    assert user32.messages == []

    clock.now += 0.2
    watchdog.check()
    assert [m[2] for m in user32.messages] == [WM_COMMAND]

    clock.now += 0.25
    watchdog.check()  # the dialog has gone
    (info,) = watchdog.disarm()
    assert info.title == "SOLIDWORKS"
    assert info.actions == ["cancel"]
    assert info.closed is True


def test_watchdog_closes_then_gives_up(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    _save_prompt(user32)  # ignores every message
    clock = _Clock()
    unanswerable: list[DialogInfo] = []
    watchdog = DialogWatchdog(
        window, 1, clock=clock, retry_seconds=1.5, on_unanswerable=unanswerable.append
    )

    watchdog.check()
    clock.now += 1.0
    watchdog.check()  # cancel
    clock.now += 1.0
    watchdog.check()  # too soon to retry
    clock.now += 1.0
    watchdog.check()  # close
    clock.now += 2.0
    watchdog.check()  # give up
    clock.now += 2.0
    watchdog.check()  # nothing more

    assert [m[2] for m in user32.messages] == [WM_COMMAND, WM_CLOSE]
    assert len(unanswerable) == 1
    assert unanswerable[0].actions == ["cancel", "close"]
    (info,) = watchdog.disarm()
    assert info.closed is False
    assert info.handed_to_user is True


def test_watchdog_thread_cancels_a_dialog(
    user32: FakeUser32, window: SolidWorksWindow
) -> None:
    _save_prompt(user32)
    _closes_on(user32, WM_COMMAND)
    watchdog = DialogWatchdog(window, 0.01, poll_seconds=0.01)

    watchdog.arm()
    thread = watchdog._thread
    watchdog.arm()  # already armed: same thread
    assert watchdog._thread is thread

    deadline = time.monotonic() + 3
    while DIALOG in user32.windows and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)  # one more poll sees it gone
    handled = watchdog.disarm()

    assert DIALOG not in user32.windows
    assert [d.actions for d in handled] == [["cancel"]]
    assert watchdog._thread is None
