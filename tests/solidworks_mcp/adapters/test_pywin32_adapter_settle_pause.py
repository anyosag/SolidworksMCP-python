"""Settle gap between adapter COM operations (COM pitfall #26).

SolidWorks 2026 SP04 / 3DEXPERIENCE crashed in its idle-time CommandManager
refresh when the API drove it back-to-back. What protects it is the gap
between one operation ending and the next one starting: 0.25 s after an
ordinary operation, 1.0 s after a document open/create/close.

By default (gap mode) the adapter waits *before* an operation for whatever is
left of the previous one's gap, and read-only operations open no gap of their
own. ``SOLIDWORKS_MCP_SETTLE_MODE=after`` restores the original fixed sleep
after every operation.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter


@pytest.fixture
def adapter(monkeypatch) -> PyWin32Adapter:
    """A ``PyWin32Adapter`` that thinks it runs on Windows with pywin32."""
    monkeypatch.setattr(
        "solidworks_mcp.adapters.pywin32_adapter.PYWIN32_AVAILABLE", True
    )
    monkeypatch.setattr(
        "solidworks_mcp.adapters.pywin32_adapter.platform.system", lambda: "Windows"
    )
    monkeypatch.setattr(
        "solidworks_mcp.adapters.pywin32_adapter.pywintypes",
        SimpleNamespace(com_error=RuntimeError),
        raising=False,
    )
    return PyWin32Adapter({})


class _Clock:
    """A monotonic clock that only moves when told to (or when slept on)."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    """Default settle values, a fake clock, and a fresh pacer."""
    fake = _Clock()
    monkeypatch.setattr(pywin32_adapter.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(pywin32_adapter.time, "sleep", fake.sleep)
    monkeypatch.delenv("SOLIDWORKS_MCP_COM_SETTLE_SECONDS", raising=False)
    monkeypatch.delenv("SOLIDWORKS_MCP_DOC_SETTLE_SECONDS", raising=False)
    monkeypatch.delenv("SOLIDWORKS_MCP_SETTLE_MODE", raising=False)
    monkeypatch.setattr(pywin32_adapter, "_PACER", pywin32_adapter._ComPacer())
    return fake


class TestSettleGap:
    """Gap mode: wait before an operation, only for what's left of the gap."""

    def test_the_first_operation_never_waits(self, adapter, clock) -> None:
        adapter._handle_com_operation("add_line", lambda: 1)

        assert clock.sleeps == []

    def test_back_to_back_operations_get_the_full_gap(self, adapter, clock) -> None:
        adapter._handle_com_operation("create_part", lambda: 1)
        adapter._handle_com_operation("add_line", lambda: 1)
        adapter._handle_com_operation("add_circle", lambda: 1)

        assert clock.sleeps == [1.0, 0.25]

    def test_time_already_spent_counts_toward_the_gap(self, adapter, clock) -> None:
        adapter._handle_com_operation("create_part", lambda: 1)
        clock.now += 0.75  # the agent took its turn
        adapter._handle_com_operation("add_line", lambda: 1)
        clock.now += 5.0
        adapter._handle_com_operation("add_circle", lambda: 1)

        assert clock.sleeps == [0.25]

    def test_a_read_waits_out_a_mutation_but_opens_no_gap(self, adapter, clock) -> None:
        adapter._handle_com_operation("create_extrusion", lambda: 1)
        adapter._handle_com_operation("get_model_geometry_summary", lambda: 1)
        adapter._handle_com_operation("list_features", lambda: 1)
        adapter._handle_com_operation("add_fillet", lambda: 1)

        # One wait, for the extrusion; the reads add none.
        assert clock.sleeps == [0.25]

    def test_a_failed_operation_still_opens_a_gap(self, adapter, clock) -> None:
        def _boom() -> None:
            raise ValueError("bad")

        result = adapter._handle_com_operation("open_model", _boom)
        adapter._handle_com_operation("add_line", lambda: 1)

        assert result.is_error
        assert clock.sleeps == [1.0]

    def test_environment_overrides(self, adapter, clock, monkeypatch) -> None:
        monkeypatch.setenv("SOLIDWORKS_MCP_COM_SETTLE_SECONDS", "0.5")
        monkeypatch.setenv("SOLIDWORKS_MCP_DOC_SETTLE_SECONDS", "3")

        adapter._handle_com_operation("add_circle", lambda: 1)
        adapter._handle_com_operation("create_assembly", lambda: 1)
        adapter._handle_com_operation("add_line", lambda: 1)

        assert clock.sleeps == [0.5, 3.0]

    def test_zero_disables_and_bad_values_fall_back(
        self, adapter, clock, monkeypatch
    ) -> None:
        monkeypatch.setenv("SOLIDWORKS_MCP_COM_SETTLE_SECONDS", "0")
        monkeypatch.setenv("SOLIDWORKS_MCP_DOC_SETTLE_SECONDS", "not-a-number")

        adapter._handle_com_operation("add_line", lambda: 1)
        adapter._handle_com_operation("create_part", lambda: 1)
        adapter._handle_com_operation("add_line", lambda: 1)

        assert clock.sleeps == [1.0]

    def test_negative_values_clamp_to_zero(self, adapter, clock, monkeypatch) -> None:
        monkeypatch.setenv("SOLIDWORKS_MCP_COM_SETTLE_SECONDS", "-2")

        adapter._handle_com_operation("add_line", lambda: 1)
        adapter._handle_com_operation("add_line", lambda: 1)

        assert clock.sleeps == []

    def test_execution_time_excludes_the_wait(self, adapter, clock) -> None:
        adapter._handle_com_operation("create_part", lambda: 1)

        result = adapter._handle_com_operation("add_line", lambda: 1)

        assert clock.sleeps == [1.0]
        assert result.execution_time < 0.5

    def test_pace_before_com_waits_out_the_gap(self, adapter, clock) -> None:
        adapter._handle_com_operation("close_model", lambda: 1)

        adapter.pace_before_com()
        adapter._handle_com_operation("get_model_info", lambda: 1)

        # pace_before_com took the whole gap; the operation itself waited 0.
        assert clock.sleeps == [1.0]

    def test_a_refused_cross_thread_call_leaves_the_gap_alone(
        self, adapter, clock
    ) -> None:
        adapter._handle_com_operation("create_part", lambda: 1)
        adapter._com_thread_id = -1  # some other thread owns COM

        refused = adapter._handle_com_operation("add_line", lambda: 1)

        assert refused.is_error
        assert clock.sleeps == []

    def test_reset_forgets_the_last_operation(self, clock) -> None:
        pacer = pywin32_adapter._ComPacer()
        pacer.mark("create_part")
        pacer.reset()

        pacer.wait()

        assert clock.sleeps == []


class TestSettleAfterMode:
    """``SOLIDWORKS_MCP_SETTLE_MODE=after``: a fixed sleep after every operation."""

    @pytest.fixture(autouse=True)
    def _after_mode(self, monkeypatch, clock) -> None:
        monkeypatch.setenv("SOLIDWORKS_MCP_SETTLE_MODE", "AFTER")

    def test_document_operations_get_the_longer_default(self, adapter, clock) -> None:
        adapter._handle_com_operation("create_part", lambda: 1)
        adapter._handle_com_operation("close_model", lambda: 1)
        adapter._handle_com_operation("add_line", lambda: 1)

        assert clock.sleeps == [1.0, 1.0, 0.25]

    def test_reads_pause_too(self, adapter, clock) -> None:
        adapter._handle_com_operation("get_model_info", lambda: 1)

        assert clock.sleeps == [0.25]

    def test_pause_runs_after_a_failed_operation(self, adapter, clock) -> None:
        def _boom() -> None:
            raise ValueError("bad")

        result = adapter._handle_com_operation("open_model", _boom)

        assert result.is_error
        assert clock.sleeps == [1.0]

    def test_pace_before_com_does_nothing(self, adapter, clock) -> None:
        adapter._handle_com_operation("create_part", lambda: 1)

        adapter.pace_before_com()

        assert clock.sleeps == [1.0]


def test_an_unknown_mode_means_gap(monkeypatch) -> None:
    monkeypatch.setenv("SOLIDWORKS_MCP_SETTLE_MODE", "sometimes")

    assert pywin32_adapter._settle_mode() == "gap"


def test_reads_never_include_an_operation_that_selects_or_rebuilds() -> None:
    """Selecting, rebuilding or changing a document triggers SolidWorks UI work."""
    for operation in (
        "check_sketch_fully_defined",
        "get_mass_properties",
        "get_selected_entities",
        "measure_entities",
        "check_interference",
        "rebuild_model",
    ):
        assert operation not in pywin32_adapter._READ_ONLY_OPERATIONS
    assert (
        not pywin32_adapter._READ_ONLY_OPERATIONS & pywin32_adapter._DOCUMENT_OPERATIONS
    )
