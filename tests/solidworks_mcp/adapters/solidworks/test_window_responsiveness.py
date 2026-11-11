"""Whether SolidWorks' frame window answers messages (``SolidWorksWindow.is_responding``)."""

from __future__ import annotations

from solidworks_mcp.adapters.solidworks.window import SolidWorksWindow

from .fake_user32 import FakeUser32

FRAME = 0x1000


def _window(**fields: object) -> tuple[SolidWorksWindow, FakeUser32]:
    user32 = FakeUser32()
    user32.add(FRAME, 9396, title="SOLIDWORKS", **fields)
    return SolidWorksWindow(FRAME, user32), user32


def test_an_idle_solidworks_answers() -> None:
    window, _user32 = _window()

    assert window.is_responding() is True


def test_a_hung_solidworks_does_not() -> None:
    window, _user32 = _window(hung=True)

    assert window.is_responding() is False


def test_a_slow_answer_counts_as_none(monkeypatch: object) -> None:
    window, user32 = _window()
    user32.SendMessageTimeoutW = lambda *_a: 0  # type: ignore[method-assign]

    assert window.is_responding(timeout_ms=10) is False


def test_a_window_that_is_gone_is_not_waited_for() -> None:
    window, user32 = _window()
    user32.remove(FRAME)

    assert window.is_responding() is True
