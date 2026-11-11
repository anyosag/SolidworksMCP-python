"""``export_image`` keeps the view for ``current`` and zooms to fit otherwise.

A user set up a close-up and exported it with ``view_orientation: "current"``;
the export zoomed to fit anyway, so a close-up could not be exported. Now
``current`` leaves the view exactly as it is (no turn, no zoom), every named
view still turns and zooms to fit, and ``zoom_to_fit`` overrides the zoom.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import bitmap
from solidworks_mcp.adapters.solidworks.window import SolidWorksWindow

from .solidworks.fake_user32 import FakeUser32

FRAME = 0x1000
OTHER_APP = 0x2000

#: Calls that change what the picture shows.
_VIEW_CHANGES = {"ShowNamedView2", "ViewZoomtofit2", "ViewZoomtofit"}


class _Doc:
    """A part document that records the view calls ``export_image`` makes."""

    def __init__(self, zoom_fails: bool = False) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.zoom_fails = zoom_fails
        # The graphics area: 16:9, like a maximized SolidWorks.
        self.ActiveView = SimpleNamespace(FrameWidth=1600, FrameHeight=900)

    def GetTitle(self) -> str:  # noqa: N802 - COM name
        return "bracket.SLDPRT"

    def GetPathName(self) -> str:  # noqa: N802 - COM name
        return ""

    def ShowNamedView2(self, name: str, view_id: int) -> None:  # noqa: N802
        self.calls.append(("ShowNamedView2", name, view_id))

    def GraphicsRedraw2(self) -> None:  # noqa: N802 - COM name
        self.calls.append(("GraphicsRedraw2",))

    def ViewZoomtofit2(self) -> None:  # noqa: N802 - COM name
        self.calls.append(("ViewZoomtofit2",))
        if self.zoom_fails:
            raise RuntimeError("COM error")

    def ViewZoomtofit(self) -> None:  # noqa: N802 - COM name
        self.calls.append(("ViewZoomtofit",))
        if self.zoom_fails:
            raise RuntimeError("COM error")

    def SaveBMP(self, path: str, width: int, height: int) -> bool:  # noqa: N802
        self.calls.append(("SaveBMP", width, height))
        bitmap.write_bmp(path, width, height, [b"\x80" * (3 * width)] * height)
        return True

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


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
    return PyWin32Adapter({})


def _attach(adapter: PyWin32Adapter, doc: _Doc) -> SimpleNamespace:
    """Make ``doc`` the active model; return the frame, which counts focus calls."""
    frame = SimpleNamespace(focused=0)
    frame.SetFocus = lambda: setattr(frame, "focused", frame.focused + 1)
    adapter.currentModel = doc
    adapter.swApp = SimpleNamespace(
        ActiveDoc=doc, Frame=frame, ActivateDoc3=lambda *_args: doc
    )
    return frame


async def _export(adapter: PyWin32Adapter, tmp_path: Path, **payload: Any) -> Any:
    result = await adapter.export_image(
        {"file_path": str(tmp_path / "shot.png"), "width": 640, "height": 480} | payload
    )
    assert result.is_success, result.error
    return result


@pytest.mark.parametrize("payload", [{}, {"view_orientation": "current"}])
async def test_current_keeps_the_view(
    adapter: PyWin32Adapter, tmp_path: Path, payload: dict[str, Any]
) -> None:
    """No turn and no zoom: only a redraw, then the picture."""
    doc = _Doc()
    _attach(adapter, doc)

    result = await _export(adapter, tmp_path, **payload)

    assert not _VIEW_CHANGES & set(doc.names())
    assert doc.names() == ["GraphicsRedraw2", "SaveBMP"]
    assert result.data["view"] == "current"
    assert result.data["zoomed_to_fit"] is False
    assert bitmap.image_size(tmp_path / "shot.png") == (640, 480)


async def test_current_is_case_insensitive(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    doc = _Doc()
    _attach(adapter, doc)

    result = await _export(adapter, tmp_path, view_orientation="Current")

    assert not _VIEW_CHANGES & set(doc.names())
    assert result.data["view"] == "current"


@pytest.mark.parametrize(
    ("orientation", "view_id"),
    [("front", 1), ("Top", 5), ("isometric", 7), ("trimetric", 9)],
)
async def test_a_named_view_turns_then_zooms_to_fit(
    adapter: PyWin32Adapter, tmp_path: Path, orientation: str, view_id: int
) -> None:
    doc = _Doc()
    _attach(adapter, doc)

    result = await _export(adapter, tmp_path, view_orientation=orientation)

    assert doc.calls[0] == ("ShowNamedView2", "", view_id)
    assert doc.names()[1:] == [
        "GraphicsRedraw2",
        "ViewZoomtofit2",
        "GraphicsRedraw2",
        "SaveBMP",
    ]
    assert result.data["view"] == orientation.lower()
    assert result.data["zoomed_to_fit"] is True


async def test_zoom_to_fit_on_current_keeps_the_turn(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    """The old ``current``: the user's angle, with the whole model in view."""
    doc = _Doc()
    _attach(adapter, doc)

    result = await _export(
        adapter, tmp_path, view_orientation="current", zoom_to_fit=True
    )

    assert "ShowNamedView2" not in doc.names()
    assert "ViewZoomtofit2" in doc.names()
    assert result.data["zoomed_to_fit"] is True


async def test_no_zoom_on_a_named_view_keeps_the_zoom(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    doc = _Doc()
    _attach(adapter, doc)

    result = await _export(
        adapter, tmp_path, view_orientation="front", zoom_to_fit=False
    )

    assert doc.names() == ["ShowNamedView2", "GraphicsRedraw2", "SaveBMP"]
    assert result.data["zoomed_to_fit"] is False


async def test_a_zoom_that_fails_is_reported(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    """Both zoom calls fail: the picture is still written, and says so."""
    doc = _Doc(zoom_fails=True)
    _attach(adapter, doc)

    result = await _export(adapter, tmp_path, view_orientation="isometric")

    assert ["ViewZoomtofit2", "ViewZoomtofit"] == [
        name for name in doc.names() if name.startswith("ViewZoom")
    ]
    assert result.data["zoomed_to_fit"] is False
    assert (tmp_path / "shot.png").exists()


async def test_current_renders_at_the_graphics_area_shape(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    """A 4:3 picture of a 16:9 view is the whole view, padded, not a crop."""
    doc = _Doc()
    _attach(adapter, doc)

    await _export(adapter, tmp_path, view_orientation="current")

    assert ("SaveBMP", 640, 360) in doc.calls
    assert bitmap.image_size(tmp_path / "shot.png") == (640, 480)


class TestMinimized:
    """SolidWorks minimized, the user working in another app."""

    @pytest.fixture
    def user32(self) -> FakeUser32:
        fake = FakeUser32()
        fake.add(FRAME, 9396, title="SOLIDWORKS", iconic=True)
        fake.add(OTHER_APP, 4242, title="Editor")
        fake.foreground = OTHER_APP
        return fake

    async def test_current_keeps_the_view_and_the_window(
        self, adapter: PyWin32Adapter, user32: FakeUser32, tmp_path: Path
    ) -> None:
        """No restore, no resize, no focus: the picture is the view as it was."""
        adapter._window = SolidWorksWindow(FRAME, user32)
        doc = _Doc()
        frame = _attach(adapter, doc)

        result = await _export(adapter, tmp_path, view_orientation="current")

        assert doc.names() == ["GraphicsRedraw2", "SaveBMP"]
        assert ("SaveBMP", 640, 360) in doc.calls  # the graphics area's 16:9
        assert result.data["zoomed_to_fit"] is False
        assert result.data["window_state"] == "minimized"
        assert user32.windows[FRAME].iconic is True
        assert user32.show_calls == []
        assert user32.foreground == OTHER_APP
        assert frame.focused == 0

    async def test_a_named_view_still_zooms(
        self, adapter: PyWin32Adapter, user32: FakeUser32, tmp_path: Path
    ) -> None:
        adapter._window = SolidWorksWindow(FRAME, user32)
        doc = _Doc()
        frame = _attach(adapter, doc)

        result = await _export(adapter, tmp_path, view_orientation="front")

        assert "ViewZoomtofit2" in doc.names()
        assert result.data["zoomed_to_fit"] is True
        assert result.data["window_state"] == "minimized"
        assert frame.focused == 0


async def test_a_visible_solidworks_is_focused(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    """Focusing a visible window doesn't move the view either."""
    doc = _Doc()
    frame = _attach(adapter, doc)

    await _export(adapter, tmp_path, view_orientation="current")

    assert frame.focused == 1
    assert not _VIEW_CHANGES & set(doc.names())
