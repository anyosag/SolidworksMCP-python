"""``export_stl_with_settings``: set the mesh options, export, put the user's back."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import stl_settings as stl
from solidworks_mcp.adapters.solidworks import window as window_module

from .solidworks.test_stl_settings import _App


@pytest.fixture(autouse=True)
def _no_keepers() -> Iterator[None]:
    yield
    for keeper in list(window_module._KEEPERS.values()):
        keeper.stop()
    window_module._KEEPERS.clear()


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> PyWin32Adapter:
    monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(pywin32_adapter.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        pywin32_adapter, "pywintypes", SimpleNamespace(com_error=RuntimeError)
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("SOLIDWORKS_MCP_KEEP_MINIMIZED", "0")
    made = PyWin32Adapter({})
    made.swApp = _App()
    made.currentModel = SimpleNamespace()
    return made


def _exported(ok: bool = True) -> AsyncMock:
    if ok:
        return AsyncMock(
            return_value=AdapterResult(
                status=AdapterResultStatus.SUCCESS, data=None, execution_time=0.4
            )
        )
    return AsyncMock(
        return_value=AdapterResult(status=AdapterResultStatus.ERROR, error="disk full")
    )


async def test_the_mesh_applies_to_the_export_and_the_users_come_back(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def export_file(path: str, fmt: str) -> AdapterResult[None]:
        seen["quality"] = adapter.swApp.values[("integer", stl.STL_QUALITY)]
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data=None)

    monkeypatch.setattr(adapter, "export_file", export_file)

    result = await adapter.export_stl_with_settings(
        "C:/out/part.stl", {"deviation_mm": 0.01, "units": "mm"}
    )

    assert result.is_success, result.error
    assert seen["quality"] == 3
    assert adapter.swApp.values[("integer", stl.STL_QUALITY)] == 2
    assert adapter.swApp.values[("integer", stl.STL_UNITS)] == 3
    assert result.data["mesh"] == {
        "applied": ["deviation 0.01 mm", "resolution custom", "units mm"],
        "restored": True,
    }


async def test_a_failed_export_still_puts_the_options_back(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter, "export_file", _exported(ok=False))

    result = await adapter.export_stl_with_settings("C:/out/p.stl", {"units": "m"})

    assert result.error == "disk full"
    assert adapter.swApp.values[("integer", stl.STL_UNITS)] == 3


async def test_options_that_cannot_be_put_back_are_reported(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter, "export_file", _exported())
    real = adapter._handle_com_operation

    def refuse_restore(name: str, func: Any, *a: Any, **k: Any) -> Any:
        if name == "restore_stl_options":
            return AdapterResult(status=AdapterResultStatus.ERROR, error="busy")
        return real(name, func, *a, **k)

    monkeypatch.setattr(adapter, "_handle_com_operation", refuse_restore)

    result = await adapter.export_stl_with_settings("C:/out/p.stl", {"binary": False})

    assert result.is_success
    assert result.data["mesh"]["restored"] is False


async def test_a_setting_solidworks_refuses_exports_nothing(
    adapter: PyWin32Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter.swApp = _App(refuse={stl.STL_UNITS})
    export = _exported()
    monkeypatch.setattr(adapter, "export_file", export)

    result = await adapter.export_stl_with_settings("C:/out/p.stl", {"units": "m"})

    assert result.is_error
    assert "did not take the STL setting units m" in (result.error or "")
    export.assert_not_awaited()


@pytest.mark.parametrize(
    ("settings", "connected", "fragment"),
    [
        ({"resolution": "coarse", "angle_deg": 5}, True, "need resolution 'custom'"),
        ({"units": "mm"}, False, "No active model"),
    ],
)
async def test_refusals_before_anything_is_set(
    adapter: PyWin32Adapter, settings: dict[str, Any], connected: bool, fragment: str
) -> None:
    if not connected:
        adapter.currentModel = None

    result = await adapter.export_stl_with_settings("C:/out/p.stl", settings)

    assert fragment in (result.error or "")
    assert adapter.swApp.writes == []
