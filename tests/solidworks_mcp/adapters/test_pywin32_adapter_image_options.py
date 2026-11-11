"""``export_image``: planes and sketches hidden for the picture, and a zoom box.

From the Cellvis dish rack: pictures of the deck were cluttered by planes and
sketches, and a close-up of one hexagon needed a zoom set by hand first.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import window as window_module
from solidworks_mcp.adapters.solidworks.visibility import DISPLAY_TOGGLES


@pytest.fixture(autouse=True)
def _no_keepers() -> Iterator[None]:
    yield
    for keeper in list(window_module._KEEPERS.values()):
        keeper.stop()
    window_module._KEEPERS.clear()


class _Extension:
    def __init__(self) -> None:
        self.toggles = dict.fromkeys(DISPLAY_TOGGLES.values(), True)

    def GetUserPreferenceToggle(self, toggle: int, _option: int) -> bool:  # noqa: N802
        return self.toggles[toggle]

    def SetUserPreferenceToggle(self, toggle: int, _option: int, on: bool) -> bool:  # noqa: N802
        self.toggles[toggle] = on
        return True


class _Doc:
    def __init__(self, writes: bool = True) -> None:
        self.Extension = _Extension()
        self.ViewZoomTo2 = Mock(return_value=None)
        self.GraphicsRedraw2 = Mock()
        self.shown_at_capture: dict[int, bool] = {}
        self.writes = writes

    def SaveAs3(self, path: str, *_args: Any) -> bool:  # noqa: N802
        self.shown_at_capture = dict(self.Extension.toggles)
        if self.writes:
            Path(path).write_bytes(b"II*")
        return self.writes


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
    made.swApp = SimpleNamespace(ActiveDoc=None, Frame=SimpleNamespace())
    made.currentModel = _Doc()
    return made


async def test_planes_and_sketches_are_hidden_for_the_picture_only(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    doc = adapter.currentModel

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "deck.tif"), "hide": ["sketches", "planes"]}
    )

    assert result.is_success, result.error
    assert result.data["hidden"] == ["planes", "sketches"]
    planes, sketches = DISPLAY_TOGGLES["planes"], DISPLAY_TOGGLES["sketches"]
    assert doc.shown_at_capture[planes] is False
    assert doc.shown_at_capture[sketches] is False
    assert doc.shown_at_capture[DISPLAY_TOGGLES["axes"]] is True
    assert doc.Extension.toggles[planes] is True  # back as it was
    assert doc.Extension.toggles[sketches] is True


async def test_a_failed_picture_still_shows_them_again(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    adapter.currentModel = _Doc(writes=False)

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "deck.tif"), "hide": ["planes"]}
    )

    assert result.is_error
    assert adapter.currentModel.Extension.toggles[DISPLAY_TOGGLES["planes"]] is True


async def test_a_zoom_box_zooms_there_in_metres(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    box = [0, 0, 0, 20, 10, 5]

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "hex.tif"), "zoom_box_mm": box}
    )

    assert result.is_success, result.error
    adapter.currentModel.ViewZoomTo2.assert_called_once_with(
        0.0, 0.0, 0.0, 0.02, 0.01, 0.005
    )
    assert result.data["zoom_box_mm"] == box
    assert result.data["zoomed_to_fit"] is False
    assert result.data["hidden"] == []


async def test_an_unknown_type_to_hide_takes_no_picture(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    result = await adapter.export_image(
        {"file_path": str(tmp_path / "x.tif"), "hide": ["planes", "ghosts"]}
    )

    assert result.error == "Unknown display type(s) to hide: ghosts"
    assert adapter.currentModel.shown_at_capture == {}
