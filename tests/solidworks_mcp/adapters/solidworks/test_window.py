"""Tests for the Win32-only SolidWorks window helper."""

from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks import window as window_module
from solidworks_mcp.adapters.solidworks.window import (
    SW_MINIMIZE,
    SW_RESTORE,
    SW_SHOWMINNOACTIVE,
    WS_EX_NOACTIVATE,
    MinimizeKeeper,
    SolidWorksWindow,
    drop_keeper,
    keeper_for,
    load_user32,
)

from .fake_user32 import FakeUser32

SW_PID = 9396
FRAME = 0x1000
OTHER_APP = 0x2000


@pytest.fixture(autouse=True)
def _fresh_keepers() -> Any:
    """Keepers are per process; don't let one leak into the next test."""
    yield
    for keeper in list(window_module._KEEPERS.values()):
        keeper.stop()
    window_module._KEEPERS.clear()


@pytest.fixture
def user32() -> FakeUser32:
    fake = FakeUser32()
    fake.add(FRAME, SW_PID, title="SOLIDWORKS")
    fake.add(OTHER_APP, 4242, title="Editor")
    fake.foreground = OTHER_APP
    fake.next_foreground = OTHER_APP
    return fake


def test_load_user32_is_none_off_windows() -> None:
    assert load_user32(platform="linux") is None


def test_load_user32_types_every_function() -> None:
    class FakeDll:
        def __init__(self, name: str, use_last_error: bool) -> None:
            self.loaded = (name, use_last_error)
            self.functions: dict[str, SimpleNamespace] = {}

        def __getattr__(self, name: str) -> SimpleNamespace:
            return self.functions.setdefault(name, SimpleNamespace())

    dll = load_user32(platform="win32", loader=FakeDll)

    assert dll.loaded == ("user32", True)
    assert set(dll.functions) == {name for name, _, _ in window_module._SIGNATURES}
    assert all(
        hasattr(f, "argtypes") and hasattr(f, "restype") for f in dll.functions.values()
    )


@pytest.mark.skipif(sys.platform != "win32", reason="needs the real user32")
def test_load_user32_loads_the_real_dll() -> None:
    dll = load_user32()
    assert dll is not None
    assert dll.IsWindow(0) == 0


def test_no_user32_means_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window_module, "load_user32", lambda: None)
    window = SolidWorksWindow(FRAME)

    assert window.available is False
    assert window.state() == "unknown"
    assert window.process_id() == 0
    assert window.foreground_window() == 0
    assert window.foreground_is_solidworks() is False
    assert window.minimize() is False
    assert window.restore() is False
    assert window.give_focus_to(OTHER_APP) is False


def test_a_closed_window_is_unknown(user32: FakeUser32) -> None:
    assert SolidWorksWindow(0x9999, user32).state() == "unknown"
    assert SolidWorksWindow(0, user32).available is False


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"visible": False}, "hidden"),
        ({"iconic": True}, "minimized"),
        ({"zoomed": True}, "maximized"),
        ({}, "normal"),
    ],
)
def test_state(user32: FakeUser32, fields: dict, expected: str) -> None:
    for name, value in fields.items():
        setattr(user32.windows[FRAME], name, value)
    window = SolidWorksWindow(FRAME, user32)

    assert window.state() == expected
    assert window.is_minimized() is (expected == "minimized")


def test_process_id(user32: FakeUser32) -> None:
    window = SolidWorksWindow(FRAME, user32)

    assert window.process_id() == SW_PID
    assert window.process_id(OTHER_APP) == 4242


def test_foreground_is_solidworks(user32: FakeUser32) -> None:
    window = SolidWorksWindow(FRAME, user32)
    assert window.foreground_window() == OTHER_APP
    assert window.foreground_is_solidworks() is False

    user32.add(0x3000, SW_PID, title="Save Modified Documents")
    user32.foreground = 0x3000  # a SolidWorks dialog counts
    assert window.foreground_is_solidworks() is True

    user32.foreground = 0
    assert window.foreground_is_solidworks() is False


def test_minimize_leaves_focus_alone_when_another_app_has_it(
    user32: FakeUser32,
) -> None:
    window = SolidWorksWindow(FRAME, user32)

    assert window.minimize() is True
    assert user32.show_calls == [(FRAME, SW_SHOWMINNOACTIVE)]
    assert user32.foreground == OTHER_APP


def test_minimize_hands_focus_on_when_solidworks_has_it(user32: FakeUser32) -> None:
    user32.foreground = FRAME
    window = SolidWorksWindow(FRAME, user32)

    assert window.minimize() is True
    assert user32.show_calls == [(FRAME, SW_MINIMIZE)]
    assert user32.foreground == OTHER_APP


def test_minimize_sends_the_focus_to_the_users_window(user32: FakeUser32) -> None:
    """Not to whatever is next in the Z-order (it was the desktop)."""
    user32.foreground = FRAME
    user32.next_foreground = 0x5000  # the desktop
    window = SolidWorksWindow(FRAME, user32)

    assert window.minimize(focus_to=OTHER_APP) is True

    assert user32.show_calls == [(FRAME, SW_SHOWMINNOACTIVE)]
    assert user32.foreground == OTHER_APP


def test_minimize_without_waiting_sends_the_focus_too(user32: FakeUser32) -> None:
    user32.foreground = FRAME
    window = SolidWorksWindow(FRAME, user32)

    assert window.minimize(wait=False, focus_to=OTHER_APP) is True
    assert user32.foreground == OTHER_APP


def test_restore(user32: FakeUser32) -> None:
    user32.windows[FRAME].iconic = True
    window = SolidWorksWindow(FRAME, user32)

    assert window.restore() is True
    assert user32.show_calls == [(FRAME, SW_RESTORE)]


def test_give_focus_to_attaches_to_the_foreground_thread(user32: FakeUser32) -> None:
    user32.foreground = FRAME  # SolidWorks took the focus
    window = SolidWorksWindow(FRAME, user32)
    own = threading.get_native_id()

    assert window.give_focus_to(OTHER_APP) is True

    assert user32.foreground == OTHER_APP
    sw_thread = SW_PID * 10
    assert user32.attach_calls == [(own, sw_thread, True), (own, sw_thread, False)]
    assert user32.attached == set()


def test_give_focus_without_a_foreground_window(user32: FakeUser32) -> None:
    user32.foreground = 0
    user32.foreground_needs_attach = False
    window = SolidWorksWindow(FRAME, user32)

    assert window.give_focus_to(OTHER_APP) is True
    assert user32.attach_calls == []


def test_give_focus_skips_attaching_to_its_own_thread(user32: FakeUser32) -> None:
    user32.windows[FRAME].thread = threading.get_native_id()
    user32.foreground = FRAME
    user32.foreground_needs_attach = False
    window = SolidWorksWindow(FRAME, user32)

    assert window.give_focus_to(OTHER_APP) is True
    assert user32.attach_calls == []


def test_give_focus_reports_failure(user32: FakeUser32) -> None:
    user32.foreground = FRAME
    window = SolidWorksWindow(FRAME, user32)
    user32.AttachThreadInput = lambda *_args: 0  # type: ignore[method-assign]

    assert window.give_focus_to(OTHER_APP) is False
    assert user32.foreground == FRAME


def test_give_focus_back_retries_while_solidworks_is_busy(user32: FakeUser32) -> None:
    user32.foreground = FRAME
    window = SolidWorksWindow(FRAME, user32)
    replies = iter([0, 0, 1])  # AttachThreadInput fails twice, then works
    real_attach = user32.AttachThreadInput

    def flaky(own: int, other: int, attach: bool) -> int:
        if attach and not next(replies):
            return 0
        return real_attach(own, other, attach)

    user32.AttachThreadInput = flaky  # type: ignore[method-assign]
    sleeps: list[float] = []

    assert window.give_focus_back(OTHER_APP, sleep=sleeps.append) is True
    assert user32.foreground == OTHER_APP
    assert sleeps == [0.1, 0.1]


def test_give_focus_back_when_solidworks_already_let_go(user32: FakeUser32) -> None:
    window = SolidWorksWindow(FRAME, user32)

    assert window.give_focus_back(OTHER_APP, sleep=pytest.fail) is True
    assert user32.attach_calls == []


def test_give_focus_back_gives_up(user32: FakeUser32) -> None:
    user32.foreground = FRAME
    user32.AttachThreadInput = lambda *_args: 0  # type: ignore[method-assign]
    window = SolidWorksWindow(FRAME, user32)
    sleeps: list[float] = []

    assert window.give_focus_back(OTHER_APP, attempts=3, sleep=sleeps.append) is False
    assert len(sleeps) == 3


def test_give_focus_back_soon_runs_on_a_thread(user32: FakeUser32) -> None:
    user32.foreground = FRAME
    window = SolidWorksWindow(FRAME, user32)

    thread = window.give_focus_back_soon(OTHER_APP)
    thread.join(timeout=2)

    assert thread.name == "solidworks-focus-return"
    assert user32.foreground == OTHER_APP


def test_block_and_allow_activation(user32: FakeUser32) -> None:
    window = SolidWorksWindow(FRAME, user32)
    original = user32.windows[FRAME].ex_style

    assert window.block_activation() is True
    assert user32.windows[FRAME].ex_style == original | WS_EX_NOACTIVATE
    window.allow_activation()

    assert user32.windows[FRAME].ex_style == original


def test_block_activation_leaves_an_existing_block_alone(user32: FakeUser32) -> None:
    user32.windows[FRAME].ex_style |= WS_EX_NOACTIVATE
    window = SolidWorksWindow(FRAME, user32)

    assert window.block_activation() is False
    assert user32.style_calls == []


def test_allow_activation_clears_a_leftover_and_is_otherwise_quiet(
    user32: FakeUser32,
) -> None:
    window = SolidWorksWindow(FRAME, user32)
    window.allow_activation()
    assert user32.style_calls == []

    user32.windows[FRAME].ex_style |= WS_EX_NOACTIVATE  # a crashed server's
    window.allow_activation()
    assert not user32.windows[FRAME].ex_style & WS_EX_NOACTIVATE


def test_activation_without_a_window(user32: FakeUser32) -> None:
    window = SolidWorksWindow(0x9999, user32)

    assert window.block_activation() is False
    window.allow_activation()
    assert user32.style_calls == []


def test_minimize_without_waiting(user32: FakeUser32) -> None:
    window = SolidWorksWindow(FRAME, user32)

    assert window.minimize(wait=False) is True
    assert user32.windows[FRAME].iconic is True


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def keeper(user32: FakeUser32) -> MinimizeKeeper:
    """A keeper on a minimized SolidWorks, the user in another app."""
    user32.windows[FRAME].iconic = True
    clock = _Clock()
    keeper = MinimizeKeeper(SolidWorksWindow(FRAME, user32), clock=clock)
    keeper.wanted = True  # without the thread; tests call check()
    keeper.clock = clock  # type: ignore[attr-defined]
    return keeper


def _solidworks_comes_up(user32: FakeUser32) -> None:
    user32.windows[FRAME].iconic = False
    user32.foreground = FRAME


def test_keeper_undoes_a_restore_while_solidworks_is_driven(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    keeper.check()  # remembers the user's window
    keeper.begin()
    _solidworks_comes_up(user32)
    user32.next_foreground = FRAME  # SolidWorks keeps the focus once minimized

    keeper.check()  # minimizes it again
    keeper.check()  # gives the focus back

    assert user32.windows[FRAME].iconic is True
    assert user32.foreground == OTHER_APP
    assert keeper.restores_undone == 1
    assert keeper.wanted is True


def test_keeper_takes_the_focus_from_a_minimized_solidworks(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    """Minimized, yet still the foreground window: give the focus back."""
    keeper.check()  # remembers the user's window
    user32.foreground = FRAME  # SolidWorks took it without restoring

    keeper.check()

    assert user32.foreground == OTHER_APP


def test_keeper_undoes_a_restore_just_after_a_com_call(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    keeper.begin()
    keeper.end()
    keeper.clock.now += 1.0  # type: ignore[attr-defined]
    _solidworks_comes_up(user32)

    keeper.check()

    assert user32.windows[FRAME].iconic is True


def test_keeper_counts_unguarded_com_calls(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    keeper.activity()  # e.g. _attempt(lambda: app.CloseAllDocuments(True))
    _solidworks_comes_up(user32)

    keeper.check()

    assert user32.windows[FRAME].iconic is True


def test_a_restore_while_idle_is_the_user(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    keeper.activity()
    keeper.clock.now += 5.0  # type: ignore[attr-defined]
    _solidworks_comes_up(user32)

    keeper.check()
    keeper.check()

    assert user32.windows[FRAME].iconic is False
    assert keeper.wanted is False


def test_keeper_leaves_solidworks_up_while_a_dialog_is_open(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    """Minimizing would hide the dialog from the watchdog and the user."""
    keeper.begin()
    _solidworks_comes_up(user32)
    user32.windows[FRAME].enabled = False  # modal dialog up

    keeper.check()

    assert user32.windows[FRAME].iconic is False
    assert keeper.restores_undone == 0


def test_keeper_shows_a_minimized_solidworks_with_a_dialog(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    """A dialog opened while minimized is hidden with its owner; show it."""
    keeper.begin()
    user32.windows[FRAME].enabled = False
    user32.foreground = OTHER_APP

    keeper.check()

    assert user32.windows[FRAME].iconic is False
    assert user32.show_calls[-1] == (FRAME, 4)  # SW_SHOWNOACTIVATE
    assert user32.foreground == OTHER_APP


def test_show_without_focus_needs_a_window(user32: FakeUser32) -> None:
    SolidWorksWindow(0x9999, user32).show_without_focus()

    assert user32.show_calls == []


def test_keeper_does_nothing_unless_wanted(
    keeper: MinimizeKeeper, user32: FakeUser32
) -> None:
    keeper.wanted = False
    keeper.begin()
    _solidworks_comes_up(user32)

    keeper.check()

    assert user32.windows[FRAME].iconic is False


def test_keeper_end_never_goes_below_zero(keeper: MinimizeKeeper) -> None:
    keeper.end()
    keeper.end()
    keeper.clock.now += 5.0  # type: ignore[attr-defined]

    assert keeper.busy is False


def test_keeper_thread_starts_with_want_and_stops(user32: FakeUser32) -> None:
    keeper = MinimizeKeeper(SolidWorksWindow(FRAME, user32), poll_seconds=0.01)
    user32.windows[FRAME].iconic = True
    keeper.begin()

    keeper.want(True)
    keeper.want(True)  # already running
    thread = keeper._thread
    _solidworks_comes_up(user32)
    deadline = time.monotonic() + 2
    while not user32.windows[FRAME].iconic and time.monotonic() < deadline:
        time.sleep(0.01)
    keeper.stop()

    assert user32.windows[FRAME].iconic is True
    assert thread is not None and not thread.is_alive()
    keeper.stop()  # stopping twice is fine


def test_keeper_thread_ends_when_no_longer_wanted(user32: FakeUser32) -> None:
    keeper = MinimizeKeeper(SolidWorksWindow(FRAME, user32), poll_seconds=0.01)
    keeper.want(True)
    thread = keeper._thread

    keeper.want(False)
    assert thread is not None
    thread.join(timeout=2)

    assert not thread.is_alive()


def test_keeper_for_is_one_per_window(user32: FakeUser32) -> None:
    first = keeper_for(SolidWorksWindow(0x7001, user32))
    again = keeper_for(SolidWorksWindow(0x7001, user32))
    other = keeper_for(SolidWorksWindow(0x7002, user32))

    assert first is again
    assert other is not first


def test_drop_keeper_stops_and_forgets_it(user32: FakeUser32) -> None:
    window = SolidWorksWindow(0x7001, user32)
    keeper = keeper_for(window)
    keeper.want(True)

    drop_keeper(window)
    drop_keeper(window)  # already gone: nothing to do

    assert keeper.wanted is False and keeper._thread is None
    assert keeper_for(window) is not keeper


def test_give_focus_to_a_closed_window(user32: FakeUser32) -> None:
    window = SolidWorksWindow(FRAME, user32)

    assert window.give_focus_to(0) is False
    assert window.give_focus_to(0x9999) is False
