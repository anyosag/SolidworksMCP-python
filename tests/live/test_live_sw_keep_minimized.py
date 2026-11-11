"""Real-SolidWorks checks for keeping SolidWorks minimized (keep-solidworks-minimized).

Each test minimizes the SolidWorks window first and checks that:

* it is still minimized after part, assembly and save calls, and the focus
  went back to the window that had it;
* ``export_image`` renders a real picture while minimized;
* saving an assembly with a modified part shows no dialog and writes both
  files, while a modified file the session didn't write needs
  ``overwrite_modified_references``;
* a blocking dialog (``RunMacro2`` on a text ``.swp``: "Cannot open") is
  cancelled and reported as ``solidworks_dialog`` instead of hanging.

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``). The window is restored at the end of each test if
it was visible before.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.adapters.base import ExtrusionParameters
from solidworks_mcp.adapters.solidworks import bitmap, saving


@pytest.fixture
def minimized(live_adapter: Any) -> Iterator[Any]:
    """Minimize the connected SolidWorks; restore it afterwards if it was up."""
    window = live_adapter._window
    assert window is not None and window.available, "no SolidWorks window handle"
    was = window.state()
    window.minimize()
    assert window.is_minimized()
    yield window
    if was in ("normal", "maximized"):
        window.restore()


def _wait_for(condition: Any, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return bool(condition())


async def _block(adapter: Any, plane: str = "Front", x: float = 0.0) -> None:
    for call in (
        lambda: adapter.create_sketch(plane),
        lambda: adapter.add_rectangle(x - 20.0, -10.0, x + 20.0, 10.0),
        adapter.exit_sketch,
        lambda: adapter.create_extrusion(ExtrusionParameters(depth=10.0)),
    ):
        result = await call()
        assert result.is_success, result.error


async def test_stays_minimized_and_gives_the_focus_back(
    live_adapter: Any, scratch: Any, minimized: Any, tmp_path: Path
) -> None:
    user_had_focus = not minimized.foreground_is_solidworks()
    part = tmp_path / "km_part.SLDPRT"
    assembly = tmp_path / "km_asm.SLDASM"
    scratch.written_files += [str(part), str(assembly)]

    assert (await live_adapter.create_part()).is_success
    assert minimized.is_minimized()
    await _block(live_adapter)
    assert (await live_adapter.save_file(str(part))).is_success
    assert (await live_adapter.create_assembly()).is_success
    assert minimized.is_minimized()
    assert (await live_adapter.insert_component(str(part), 0.0, 0.0, 0.0)).is_success
    assert (await live_adapter.save_file(str(assembly))).is_success

    assert minimized.is_minimized()
    if user_had_focus:
        assert _wait_for(lambda: not minimized.foreground_is_solidworks())


async def test_screenshot_while_minimized(
    live_adapter: Any, scratch: Any, minimized: Any, tmp_path: Path
) -> None:
    assert (await live_adapter.create_part()).is_success
    await _block(live_adapter)
    image = tmp_path / "km_shot.bmp"

    result = await live_adapter.export_image(
        {
            "file_path": str(image),
            "width": 800,
            "height": 600,
            "view_orientation": "isometric",
        }
    )

    assert result.is_success, result.error
    assert result.data["window_state"] == "minimized"
    width, height, rows = bitmap.read_bmp(image)
    assert (width, height) == (800, 600)
    assert (
        len({row[i : i + 3] for row in rows[::20] for i in range(0, len(row), 60)}) > 5
    )
    assert minimized.is_minimized()


async def _assembly_with_modified_part(
    adapter: Any, scratch: Any, tmp_path: Path
) -> tuple[Path, Path]:
    """A saved part in a saved assembly, then the part changed (unsaved)."""
    part = tmp_path / "km_rail.SLDPRT"
    assembly = tmp_path / "km_rack.SLDASM"
    scratch.written_files += [str(part), str(assembly)]
    assert (await adapter.create_part()).is_success
    await _block(adapter)
    assert (await adapter.save_file(str(part))).is_success
    assert (await adapter.create_assembly()).is_success
    assert (await adapter.insert_component(str(part), 0.0, 0.0, 0.0)).is_success
    assert (await adapter.save_file(str(assembly))).is_success

    assert (await adapter.activate_document(str(part))).is_success
    await _block(adapter, plane="Top", x=40.0)
    activated = await adapter.activate_document(str(assembly))
    assert activated.is_success, activated.error
    return part, assembly


async def test_assembly_save_writes_the_sessions_part_without_a_dialog(
    live_adapter: Any, scratch: Any, minimized: Any, tmp_path: Path
) -> None:
    part, assembly = await _assembly_with_modified_part(live_adapter, scratch, tmp_path)
    part_before = part.stat().st_mtime

    result = await live_adapter.save_file(None)

    assert result.is_success, result.error  # a dialog would be solidworks_dialog
    assert part.stat().st_mtime != part_before
    assert saving.normalize(str(part)) in {
        saving.normalize(p) for p in result.data["saved_references"]
    }
    assert minimized.is_minimized()


async def test_assembly_save_over_a_users_part_needs_confirmation(
    live_adapter: Any, scratch: Any, minimized: Any, tmp_path: Path
) -> None:
    part, assembly = await _assembly_with_modified_part(live_adapter, scratch, tmp_path)
    # Make the part "the user's": a file this session didn't write.
    saving.session_paths(live_adapter).discard(saving.normalize(str(part)))
    part_before = part.stat().st_mtime
    assembly_before = assembly.stat().st_mtime

    refused = await live_adapter.save_file(None)

    assert refused.is_error
    assert refused.data["confirm_with"] == "overwrite_modified_references"
    assert part.stat().st_mtime == part_before
    assert assembly.stat().st_mtime == assembly_before

    confirmed = await live_adapter.save_file(None, True)

    assert confirmed.is_success, confirmed.error
    assert part.stat().st_mtime != part_before


async def test_a_blocking_dialog_is_cancelled(
    live_adapter: Any, minimized: Any, tmp_path: Path
) -> None:
    macro = tmp_path / "km_text_macro.swp"
    macro.write_text(
        'Attribute VB_Name = "Km"\nSub main()\nEnd Sub\n', encoding="utf-8"
    )
    started = time.monotonic()

    result = await live_adapter.execute_macro({"macro_path": str(macro)})

    assert result.is_error
    assert "SolidWorks showed a dialog during execute_macro" in (result.error or "")
    assert result.data["dialog"]["actions"][0] == "cancel"
    assert time.monotonic() - started < 15
    # SolidWorks still answers.
    assert (await live_adapter.list_open_documents()).is_success
