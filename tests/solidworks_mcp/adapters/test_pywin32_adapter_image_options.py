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
    assert result.data["zoom_box_view_mm"] is None  # no view orientation to read
    assert result.data["zoomed_to_fit"] is False
    assert result.data["hidden"] == []


async def test_a_zoom_box_in_the_right_view_is_turned_into_view_coordinates(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    """ViewZoomTo2 takes view coordinates: the Cellvis right-view close-up."""
    right_view = SimpleNamespace(Orientation3="right")
    adapter.currentModel.ActiveView = right_view
    adapter.currentModel.ShowNamedView2 = Mock()

    class _Point:
        def __init__(self, data: Any) -> None:
            self.ArrayData = tuple(getattr(data, "value", data))

        def MultiplyTransform(self, _orientation: Any) -> Any:  # noqa: N802
            x, y, z = self.ArrayData
            return _Point([-z, y, x])

    adapter.swApp.GetMathUtility = lambda: SimpleNamespace(CreatePoint=_Point)

    result = await adapter.export_image(
        {
            "file_path": str(tmp_path / "latch.tif"),
            "view_orientation": "right",
            "zoom_box_mm": [29, -2, -11, 31, 22, 11],
        }
    )

    assert result.is_success, result.error
    args = adapter.currentModel.ViewZoomTo2.call_args.args
    assert args == pytest.approx((-0.011, -0.002, 0.029, 0.011, 0.022, 0.031))
    assert result.data["zoom_box_view_mm"] == [-11.0, -2.0, 29.0, 11.0, 22.0, 31.0]


async def test_an_unknown_type_to_hide_takes_no_picture(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    result = await adapter.export_image(
        {"file_path": str(tmp_path / "x.tif"), "hide": ["planes", "ghosts"]}
    )

    assert result.error == "Unknown display type(s) to hide: ghosts"
    assert adapter.currentModel.shown_at_capture == {}


# ---- section: a plane cut for one picture ---------------------------------------


class _SectionDoc(_Doc):
    """A document with Front Plane and a view manager, logging what happens."""

    def __init__(self, writes: bool = True, removes: bool = True) -> None:
        super().__init__(writes)
        self.events: list[str] = []
        self.ShowNamedView2 = lambda *_a: self.events.append("turn")
        self.ViewZoomTo2 = lambda *_a: self.events.append("zoom")
        self.data = SimpleNamespace()
        doc = self

        class _Manager:
            def CreateSectionViewData(self) -> Any:  # noqa: N802
                return doc.data

            def CreateSectionView(self, data: Any) -> bool:  # noqa: N802
                doc.events.append("section")
                return True

            def RemoveSectionView(self) -> bool:  # noqa: N802
                doc.events.append("removed")
                return removes

        self.ModelViewManager = _Manager()

    def FeatureByName(self, name: str) -> Any:  # noqa: N802
        self.events.append(f"find {name}")
        if name != "Front Plane":
            return None
        return SimpleNamespace(
            GetTypeName2=lambda: "RefPlane", GetSpecificFeature2=lambda: "front"
        )

    def SaveAs3(self, path: str, *args: Any) -> bool:  # noqa: N802
        self.events.append("picture")
        return super().SaveAs3(path, *args)


async def test_a_section_cuts_the_picture_and_is_taken_off(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    doc = adapter.currentModel = _SectionDoc()

    result = await adapter.export_image(
        {
            "file_path": str(tmp_path / "latch.tif"),
            "view_orientation": "front",
            "zoom_box_mm": [0, 0, 0, 10, 10, 10],
            "hide": ["planes"],
            "section": {"plane": "Front Plane", "offset_mm": 1.5, "reverse": True},
        }
    )

    assert result.is_success, result.error
    # Found first, cut after the turn and before the zoom, off after the picture.
    assert doc.events[0] == "find Front Plane"
    assert doc.events.index("turn") < doc.events.index("section")
    assert doc.events.index("section") < doc.events.index("zoom")
    assert doc.events.index("picture") < doc.events.index("removed")
    assert (doc.data.FirstPlane, doc.data.FirstOffset) == ("front", 0.0015)
    assert doc.data.FirstReverseDirection is True
    assert doc.data.ShowSectionCap is True
    assert result.data["section"] == {
        "plane": "Front Plane",
        "offset_mm": 1.5,
        "reverse": True,
        "removed": True,
    }
    assert result.data["hidden"] == ["planes"]


async def test_an_unknown_plane_takes_no_picture(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    doc = adapter.currentModel = _SectionDoc()

    result = await adapter.export_image(
        {
            "file_path": str(tmp_path / "x.tif"),
            "view_orientation": "front",
            "hide": ["planes"],
            "section": {"plane": "Plane7"},
        }
    )

    assert result.is_error
    assert "Section plane not found: the model has no plane named 'Plane7'" in (
        result.error or ""
    )
    # Not turned, nothing hidden, no picture: the model is as it was.
    assert doc.events == ["find Plane7"]
    assert all(doc.Extension.toggles.values())
    assert not (tmp_path / "x.tif").exists()


async def test_a_failed_picture_still_takes_the_section_off(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    doc = adapter.currentModel = _SectionDoc(writes=False)

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "x.tif"), "section": {"plane": "Front Plane"}}
    )

    assert result.is_error
    assert doc.events[-1] == "removed"


async def test_a_section_that_stays_on_is_reported(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    adapter.currentModel = _SectionDoc(removes=False)

    result = await adapter.export_image(
        {"file_path": str(tmp_path / "x.tif"), "section": {"plane": "Front Plane"}}
    )

    assert result.is_success, result.error
    assert result.data["section"]["removed"] is False


async def test_without_a_section_none_is_reported(
    adapter: PyWin32Adapter, tmp_path: Path
) -> None:
    doc = adapter.currentModel = _SectionDoc()

    result = await adapter.export_image({"file_path": str(tmp_path / "x.tif")})

    assert result.data["section"] is None
    assert "section" not in doc.events and "removed" not in doc.events
