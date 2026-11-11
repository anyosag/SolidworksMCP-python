"""Reconnecting after the connected SolidWorks has exited.

Once SolidWorks restarts, every call on the old ``swApp`` fails with
``RPC_S_SERVER_UNAVAILABLE``. ``_handle_com_operation`` notices (the frame
window is gone, or, without a window, a failed call's ``RevisionNumber`` probe
gets an RPC error), binds to the running SolidWorks with ``GetActiveObject``
and returns an error for that one call; the next call runs as usual.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter, _hresult_of
from solidworks_mcp.adapters.solidworks import window as window_module
from solidworks_mcp.adapters.solidworks.window import SolidWorksWindow, keeper_for
from solidworks_mcp.tools.error_classifier import ErrorClassifier

from .solidworks.fake_user32 import FakeUser32

OLD_PID = 9396
NEW_PID = 48816
OLD_FRAME = 0x1000
NEW_FRAME = 0x5000
OTHER_APP = 0x2000
RPC_S_SERVER_UNAVAILABLE = -2147023174


class _Frame:
    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd

    def GetHWnd(self) -> int:  # noqa: N802 - COM name
        return self.hwnd


class _App:
    """A ``SldWorks.Application`` with a frame window and preference toggles."""

    def __init__(self, hwnd: int, revision: object = "34.4.1") -> None:
        self.hwnd = hwnd
        self.revision = revision
        self.toggles: list[tuple[int, bool]] = []
        self.toggle_error: Exception | None = None
        self.Visible = True

    @property
    def RevisionNumber(self) -> object:  # noqa: N802 - COM name
        if isinstance(self.revision, BaseException):
            raise self.revision
        return self.revision

    def Frame(self) -> _Frame:  # noqa: N802
        return _Frame(self.hwnd)

    def SetUserPreferenceToggle(self, preference: int, value: bool) -> None:  # noqa: N802
        if self.toggle_error is not None:
            raise self.toggle_error
        self.toggles.append((preference, value))


def _gone() -> RuntimeError:
    """What a call on a SolidWorks that has exited raises."""
    return RuntimeError(RPC_S_SERVER_UNAVAILABLE, "The RPC server is unavailable.")


@pytest.fixture(autouse=True)
def _fresh_keepers() -> Any:
    yield
    for keeper in list(window_module._KEEPERS.values()):
        keeper.stop()
    window_module._KEEPERS.clear()


@pytest.fixture
def user32() -> FakeUser32:
    fake = FakeUser32()
    fake.add(OLD_FRAME, OLD_PID, title="SOLIDWORKS")
    fake.add(OTHER_APP, 4242, title="Editor")
    fake.foreground = OTHER_APP
    return fake


@pytest.fixture
def running(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What ``GetActiveObject`` finds: ``app`` (``None``: SolidWorks isn't running)."""
    state: dict[str, Any] = {"app": None, "calls": 0}

    def get_active_object(prog_id: str) -> Any:
        assert prog_id == "SldWorks.Application"
        state["calls"] += 1
        if state["app"] is None:
            raise RuntimeError(-2147221021, "Operation unavailable")
        return state["app"]

    monkeypatch.setattr(
        pywin32_adapter,
        "win32com",
        SimpleNamespace(client=SimpleNamespace(GetActiveObject=get_active_object)),
    )
    monkeypatch.setattr(
        pywin32_adapter, "_dynamic_module", SimpleNamespace(Dispatch=lambda raw: raw)
    )
    return state


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch, user32: FakeUser32) -> PyWin32Adapter:
    monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(pywin32_adapter.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        pywin32_adapter, "pywintypes", SimpleNamespace(com_error=RuntimeError)
    )
    monkeypatch.setattr(
        pywin32_adapter, "SolidWorksWindow", lambda hwnd: SolidWorksWindow(hwnd, user32)
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS", "0")
    monkeypatch.delenv("SOLIDWORKS_MCP_HEADLESS", raising=False)
    return PyWin32Adapter({})


@pytest.fixture
def connected(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> PyWin32Adapter:
    """Connected to the SolidWorks with ``OLD_FRAME``, a part and sketch open."""
    coordinator = adapter._session_coordinator
    monkeypatch.setattr(coordinator, "initialize_com_apartment", lambda: None)
    monkeypatch.setattr(coordinator, "uninitialize_com_apartment", lambda: None)
    old = _App(OLD_FRAME)

    async def acquire() -> Any:
        adapter.swApp = old
        return old

    monkeypatch.setattr(coordinator, "acquire_solidworks_application", acquire)
    asyncio.run(adapter.connect())
    adapter.currentModel = "Part1"
    adapter.currentSketch = "Sketch1"
    adapter._last_sketch_name = "Sketch1"
    adapter._sketch_entities["Line_1"] = object()
    return adapter


def _restart(user32: FakeUser32, running: dict[str, Any], pid: int = NEW_PID) -> _App:
    """SolidWorks exits and a new one starts."""
    user32.remove(OLD_FRAME)
    user32.add(NEW_FRAME, pid, title="SOLIDWORKS")
    running["app"] = new = _App(NEW_FRAME)
    return new


def _never_run() -> None:
    raise AssertionError("the operation ran")


def test_connect_records_the_solidworks_process(connected: PyWin32Adapter) -> None:
    assert connected._sw_process_id == OLD_PID
    assert connected._solidworks_lost is False


def test_a_call_while_solidworks_runs_does_not_look_for_another(
    connected: PyWin32Adapter, running: dict[str, Any]
) -> None:
    result = connected._handle_com_operation("add_line", lambda: "line")

    assert result.is_success and result.data == "line"
    assert running["calls"] == 0


def test_a_call_after_a_restart_reconnects_without_running(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    new = _restart(user32, running)

    result = connected._handle_com_operation("create_extrusion", _never_run)

    assert result.is_error
    assert "create_extrusion was not run" in str(result.error)
    assert ErrorClassifier().classify(str(result.error)).error_type == (
        "solidworks_reconnected"
    )
    assert connected.swApp is new
    assert connected._sw_process_id == NEW_PID
    assert connected._window is not None and connected._window.hwnd == NEW_FRAME
    assert connected._solidworks_lost is False
    # Automation preferences were set on the new SolidWorks.
    assert (150, False) in new.toggles
    # Nothing of the old SolidWorks' documents survives.
    assert connected.currentModel is None
    assert connected.currentSketch is None
    assert connected._last_sketch_name is None
    assert connected._sketch_entities == {}


def test_the_call_after_that_runs_on_the_new_solidworks(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    _restart(user32, running)
    connected._handle_com_operation("create_extrusion", _never_run)

    result = connected._handle_com_operation("list_open_documents", lambda: [])

    assert result.is_success
    assert running["calls"] == 1


def test_no_solidworks_running_keeps_trying_on_each_call(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    old = connected.swApp
    user32.remove(OLD_FRAME)

    first = connected._handle_com_operation("add_line", _never_run)
    second = connected._handle_com_operation("add_line", _never_run)

    for result in (first, second):
        assert result.is_error
        assert "SolidWorks is not running now" in str(result.error)
        assert ErrorClassifier().classify(str(result.error)).error_type == (
            "solidworks_unavailable"
        )
    assert running["calls"] == 2
    assert connected._solidworks_lost is True
    # The old handle stays, so is_connected() still lets calls reach here.
    assert connected.swApp is old and connected.is_connected()
    assert connected._window is None

    user32.add(NEW_FRAME, NEW_PID)
    running["app"] = _App(NEW_FRAME)
    assert "has reconnected" in str(
        connected._handle_com_operation("add_line", _never_run).error
    )
    assert connected._handle_com_operation("add_line", lambda: "line").is_success


def test_a_solidworks_still_starting_is_tried_again(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    new = _restart(user32, running)
    new.revision = RuntimeError("starting")

    result = connected._handle_com_operation("add_line", _never_run)

    assert "not answering yet" in str(result.error)
    assert ErrorClassifier().classify(str(result.error)).error_type == (
        "solidworks_unavailable"
    )
    assert connected._solidworks_lost is True

    new.revision = "34.4.1"
    assert "has reconnected" in str(
        connected._handle_com_operation("add_line", _never_run).error
    )


def test_a_failed_setup_is_tried_again_in_full(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    """Setup failed once: the next try sets the new SolidWorks up again."""
    new = _restart(user32, running)
    new.toggle_error = RuntimeError("busy")

    result = connected._handle_com_operation("add_line", _never_run)

    assert "not answering yet" in str(result.error)
    assert connected._sw_process_id == OLD_PID
    assert connected._window is None

    new.toggle_error = None
    result = connected._handle_com_operation("add_line", _never_run)
    assert "has reconnected" in str(result.error)
    assert (150, False) in new.toggles


def test_the_same_solidworks_with_a_new_window_runs_the_call(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    """A false alarm: the window changed, the process didn't."""
    same = _restart(user32, running, pid=OLD_PID)

    result = connected._handle_com_operation("add_line", lambda: "line")

    assert result.is_success and result.data == "line"
    assert connected.swApp is same
    assert connected._window is not None and connected._window.hwnd == NEW_FRAME
    assert connected.currentModel == "Part1"
    assert same.toggles == []


def test_a_call_that_fails_as_solidworks_exits_reconnects(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    def exits() -> None:
        _restart(user32, running)
        raise _gone()

    result = connected._handle_com_operation("create_extrusion", exits)

    assert "create_extrusion failed" in str(result.error)
    assert "has reconnected" in str(result.error)


def test_a_failure_while_the_window_changes_keeps_its_own_error(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    def fails() -> None:
        _restart(user32, running, pid=OLD_PID)
        raise ValueError("no faces")

    result = connected._handle_com_operation("add_fillet", fails)

    assert result.error == "Error in add_fillet: no faces"
    assert connected._solidworks_lost is False


class TestWithoutAWindow:
    """No frame handle: a failed call probes ``RevisionNumber`` instead."""

    @pytest.fixture
    def windowless(self, connected: PyWin32Adapter) -> PyWin32Adapter:
        connected._window = None
        connected._keeper = None
        connected._sw_process_id = 0
        return connected

    def test_a_successful_call_makes_no_probe(
        self, windowless: PyWin32Adapter, running: dict[str, Any]
    ) -> None:
        windowless.swApp.revision = _gone()  # type: ignore[union-attr]

        assert windowless._handle_com_operation("add_line", lambda: 1).is_success
        assert running["calls"] == 0

    def test_a_failed_call_on_a_dead_solidworks_reconnects(
        self,
        windowless: PyWin32Adapter,
        user32: FakeUser32,
        running: dict[str, Any],
    ) -> None:
        windowless.swApp.revision = _gone()  # type: ignore[union-attr]
        new = _restart(user32, running)

        def dead() -> None:
            raise _gone()

        result = windowless._handle_com_operation("add_line", dead)

        assert "add_line failed" in str(result.error)
        assert "has reconnected" in str(result.error)
        assert windowless.swApp is new
        assert windowless._sw_process_id == NEW_PID

    @pytest.mark.parametrize(
        "revision",
        ["34.4.1", ValueError("odd"), RuntimeError("not an hresult")],
        ids=["answers", "other-error", "no-hresult"],
    )
    def test_a_failed_call_on_a_running_solidworks_keeps_its_error(
        self, windowless: PyWin32Adapter, running: dict[str, Any], revision: object
    ) -> None:
        windowless.swApp.revision = revision  # type: ignore[union-attr]

        def fails() -> None:
            raise ValueError("no faces")

        result = windowless._handle_com_operation("add_fillet", fails)

        assert result.error == "Error in add_fillet: no faces"
        assert running["calls"] == 0


def test_nested_operations_leave_it_to_the_outermost(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    connected._operation_depth = 1
    user32.remove(OLD_FRAME)

    assert connected._handle_com_operation("inner", lambda: 1).is_success
    assert running["calls"] == 0


def test_an_unconnected_adapter_is_not_reconnected(
    adapter: PyWin32Adapter, running: dict[str, Any]
) -> None:
    def fails() -> None:
        raise _gone()

    result = adapter._handle_com_operation("add_line", fails)

    assert result.is_error and "has reconnected" not in str(result.error)
    assert running["calls"] == 0


def test_the_old_windows_keeper_is_stopped(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    old_keeper = keeper_for(SolidWorksWindow(OLD_FRAME, user32))
    old_keeper.want(True)
    _restart(user32, running)

    connected._handle_com_operation("add_line", _never_run)

    assert old_keeper.wanted is False
    assert old_keeper._thread is None
    assert OLD_FRAME not in window_module._KEEPERS


async def test_disconnect_forgets_the_lost_solidworks(
    connected: PyWin32Adapter, user32: FakeUser32, running: dict[str, Any]
) -> None:
    user32.remove(OLD_FRAME)
    connected._handle_com_operation("add_line", _never_run)
    assert connected._solidworks_lost is True

    await connected.disconnect()

    assert connected._solidworks_lost is False
    assert connected._sw_process_id == 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, None),
        (ValueError(RPC_S_SERVER_UNAVAILABLE), None),
        (RuntimeError(), None),
        (RuntimeError("text"), None),
        (RuntimeError(RPC_S_SERVER_UNAVAILABLE, "gone"), RPC_S_SERVER_UNAVAILABLE),
    ],
)
def test_hresult_of(
    adapter: PyWin32Adapter, error: BaseException | None, expected: int | None
) -> None:
    """``com_error`` is ``RuntimeError`` here (the adapter fixture patches it)."""
    assert _hresult_of(error) == expected
