"""Probe what a minimized SolidWorks does to its window, focus and dialogs.

Task 1.3 of the ``keep-solidworks-minimized`` OpenSpec change. It drives the
running SolidWorks through ``PyWin32Adapter`` with the window minimized and
records, after every step:

* the window state (``minimized`` / ``normal`` / ...) right when the call
  returns and again 1.5 s later (to catch SolidWorks restoring itself late),
* whether SolidWorks took the foreground (keyboard focus),
* any modal dialog it showed. A watchdog cancels a dialog after 5 s, so the
  probe never hangs; it never presses Save or Don't Save.

Modes:

* default: a part, screenshots while minimized (``export_image`` and a raw
  ``SaveBMP``, each checked for content), an assembly, a drawing, closing a
  modified part.
* ``--saves``: the save prompts. An assembly saved in place and closed with
  ``save`` after one of its parts changed, with the part file's modified
  time before and after; and a timeline of the window during
  ``create_part`` (how long SolidWorks is visible).

It only touches documents it creates: open documents from before the run are
never closed or saved, and the SolidWorks files it writes are deleted at the
end. The report and the images stay in ``tests/.generated/probe_minimized/``.

Usage (SolidWorks running, the user's work saved)::

    .venv\\Scripts\\python.exe tests/scripts/probe_minimized.py [--saves]
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from solidworks_mcp.adapters import sw_type_info
from solidworks_mcp.adapters.base import ExtrusionParameters
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import bitmap
from solidworks_mcp.adapters.solidworks.dialogs import DialogWatchdog
from solidworks_mcp.adapters.solidworks.window import SolidWorksWindow

OUT = Path(__file__).resolve().parents[1] / ".generated" / "probe_minimized"
LATE_CHECK_SECONDS = 1.5
DIALOG_TIMEOUT_SECONDS = 5.0


def _frame_window(adapter: PyWin32Adapter) -> SolidWorksWindow:
    frame = adapter._get_attr_or_call(adapter.swApp, "Frame")
    return SolidWorksWindow(int(adapter._get_attr_or_call(frame, "GetHWnd")))


def _colours(bmp_path: Path) -> dict[str, Any]:
    """Size and number of distinct colours of a BMP (1 means blank)."""
    if not bmp_path.exists():
        return {"written": False}
    width, height, rows = bitmap.read_bmp(bmp_path)
    step_x = 3 * max(1, width // 80)
    colours = {
        row[i : i + 3]
        for row in rows[:: max(1, height // 60)]
        for i in range(0, len(row), step_x)
    }
    return {"written": True, "size": [width, height], "distinct_colours": len(colours)}


def _mtime(path: Path) -> float | None:
    return path.stat().st_mtime if path.exists() else None


class Probe:
    """Runs steps and records what the window did."""

    def __init__(self, adapter: PyWin32Adapter, window: SolidWorksWindow) -> None:
        self.adapter = adapter
        self.window = window
        self.steps: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.window.state(),
            "foreground_is_solidworks": self.window.foreground_is_solidworks(),
        }

    async def step(
        self, name: str, call: Callable[[], Awaitable[Any]], **extra: Any
    ) -> Any:
        """Run one step minimized and record it."""
        if not self.window.is_minimized():
            self.window.minimize()
        before = self.snapshot()
        watchdog = DialogWatchdog(
            self.window,
            DIALOG_TIMEOUT_SECONDS,
            on_unanswerable=lambda _info: self.window.restore(),
        )
        watchdog.arm()
        started = time.monotonic()
        result: Any = None
        error = None
        data = None
        try:
            result = await call()
            ok = getattr(result, "is_success", True)
            error = getattr(result, "error", None)
            data = getattr(result, "data", None)
        except Exception as exc:  # noqa: BLE001 - a probe records, it doesn't stop
            ok = False
            error = repr(exc)
        finally:
            dialogs = watchdog.disarm()
        seconds = round(time.monotonic() - started, 2)
        on_return = self.snapshot()
        time.sleep(LATE_CHECK_SECONDS)
        late = self.snapshot()
        adapter_dialog = data.get("dialog") if isinstance(data, dict) else None
        record = {
            "step": name,
            "ok": ok,
            "error": error,
            "seconds": seconds,
            "before": before,
            "on_return": on_return,
            "after_1_5s": late,
            "dialogs": [d.to_dict() for d in dialogs],
            "adapter_dialog": adapter_dialog,
            **extra,
        }
        self.steps.append(record)
        changed = on_return["state"] != "minimized" or late["state"] != "minimized"
        focus = (
            on_return["foreground_is_solidworks"] or late["foreground_is_solidworks"]
        )
        shown = [d.summary() for d in dialogs]
        if adapter_dialog:
            shown.append(
                f"(adapter) {adapter_dialog.get('title')}: {adapter_dialog.get('texts')}"
            )
        print(
            f"[probe] {name}: ok={ok} {seconds}s {on_return['state']}->{late['state']}"
            + ("  <-- window changed" if changed else "")
            + ("  <-- took focus" if focus else "")
            + (f"  dialogs: {shown}" if shown else "")
        )
        if not ok:
            print(f"[probe]   error: {error}")
        return result

    def save_bmp(
        self, path: Path, width: int = 800, height: int = 600
    ) -> dict[str, Any]:
        """A raw ``SaveBMP`` of the active document; returns its colour check."""
        doc = self.adapter.swApp.ActiveDoc
        self.adapter._attempt(lambda: sw_type_info.flag_members(doc, "SaveBMP"))
        self.adapter._attempt(lambda: doc.GraphicsRedraw2())
        view = self.adapter._attempt(lambda: doc.ActiveView)
        frame = [
            self.adapter._attempt(lambda n=n: int(getattr(view, n)))
            for n in ("FrameWidth", "FrameHeight")
        ]
        returned = self.adapter._attempt(
            lambda: doc.SaveBMP(str(path), width, height), default=None
        )
        return {"returned": returned, "graphics_frame": frame, **_colours(path)}


async def _open_titles(adapter: PyWin32Adapter) -> dict[str, str]:
    listing = await adapter.list_open_documents()
    docs = list(listing.data or []) if listing.is_success else []
    return {d.get("title", ""): d.get("path", "") for d in docs}


async def _build_part(
    probe: Probe, adapter: PyWin32Adapter, plane: str = "Front"
) -> None:
    await probe.step("create_part", lambda: adapter.create_part())
    await probe.step("create_sketch", lambda: adapter.create_sketch(plane))
    await probe.step(
        "add_rectangle", lambda: adapter.add_rectangle(-20.0, -10.0, 20.0, 10.0)
    )
    await probe.step("exit_sketch", adapter.exit_sketch)
    await probe.step(
        "create_extrusion",
        lambda: adapter.create_extrusion(ExtrusionParameters(depth=10.0)),
    )


async def _modify_part(
    probe: Probe, adapter: PyWin32Adapter, part: Path, n: int
) -> None:
    """Activate the part and add a small boss, so it has unsaved changes."""
    await probe.step(f"activate_part_{n}", lambda: adapter.activate_document(str(part)))
    await probe.step(f"part_sketch_{n}", lambda: adapter.create_sketch("Top"))
    offset = 20.0 + 6.0 * n
    await probe.step(
        f"part_rectangle_{n}",
        lambda: adapter.add_rectangle(offset, offset, offset + 4.0, offset + 4.0),
    )
    await probe.step(f"part_exit_sketch_{n}", adapter.exit_sketch)
    await probe.step(
        f"part_extrusion_{n}",
        lambda: adapter.create_extrusion(ExtrusionParameters(depth=3.0)),
    )


def _timeline(window: SolidWorksWindow, stop: threading.Event) -> list[list[Any]]:
    """Poll the window every 20 ms until ``stop``; record each change."""
    changes: list[list[Any]] = []
    started = time.monotonic()
    last = None
    while not stop.is_set():
        now = (window.state(), window.foreground_is_solidworks())
        if now != last:
            changes.append([round(time.monotonic() - started, 3), *now])
            last = now
        time.sleep(0.02)
    return changes


async def run_full(
    adapter: PyWin32Adapter, probe: Probe, report: dict, out: Path, scratch: Path
) -> None:
    part_path = scratch / "probe_part.SLDPRT"
    asm_path = scratch / "probe_asm.SLDASM"
    await _build_part(probe, adapter)
    await probe.step("save_part", lambda: adapter.save_file(str(part_path)))

    image = out / "export_image.png"
    await probe.step(
        "export_image",
        lambda: adapter.export_image(
            {
                "file_path": str(image),
                "width": 800,
                "height": 600,
                "view_orientation": "isometric",
            }
        ),
    )
    probe.window.minimize()
    report["screenshots"] = {
        "export_image": {
            "written": image.exists(),
            "size": bitmap.image_size(image) if image.exists() else None,
        },
        "savebmp_minimized": probe.save_bmp(out / "savebmp_minimized.bmp"),
    }
    print(f"[probe] screenshots: {json.dumps(report['screenshots'])}")

    await probe.step("create_assembly", lambda: adapter.create_assembly())
    await probe.step(
        "insert_component",
        lambda: adapter.insert_component(str(part_path), 0.0, 0.0, 0.0),
    )
    await _modify_part(probe, adapter, part_path, 1)
    await probe.step(
        "save_assembly_as (part modified)", lambda: adapter.save_file(str(asm_path))
    )
    await probe.step("create_drawing", lambda: adapter.create_drawing())
    await probe.step("close_drawing", lambda: adapter.close_model(save=False))
    await _modify_part(probe, adapter, part_path, 2)
    await probe.step(
        "close_modified_part (no save)", lambda: adapter.close_model(save=False)
    )


async def run_saves(
    adapter: PyWin32Adapter, probe: Probe, report: dict, out: Path, scratch: Path
) -> None:
    part_path = scratch / "saves_part.SLDPRT"
    asm_path = scratch / "saves_asm.SLDASM"

    stop = threading.Event()
    changes: list[list[Any]] = []
    poller = threading.Thread(
        target=lambda: changes.extend(_timeline(probe.window, stop)), daemon=True
    )
    poller.start()
    await probe.step("create_part (timed)", lambda: adapter.create_part())
    stop.set()
    poller.join()
    report["create_part_timeline"] = changes
    print(f"[probe] create_part timeline [s, state, solidworks_has_focus]: {changes}")

    await probe.step("create_sketch", lambda: adapter.create_sketch("Front"))
    await probe.step(
        "add_rectangle", lambda: adapter.add_rectangle(-20.0, -10.0, 20.0, 10.0)
    )
    await probe.step("exit_sketch", adapter.exit_sketch)
    await probe.step(
        "create_extrusion",
        lambda: adapter.create_extrusion(ExtrusionParameters(depth=10.0)),
    )
    await probe.step("save_part", lambda: adapter.save_file(str(part_path)))
    await probe.step("create_assembly", lambda: adapter.create_assembly())
    asm_title = next(
        (t for t, p in (await _open_titles(adapter)).items() if not p), "Assem1"
    )
    await probe.step(
        "insert_component",
        lambda: adapter.insert_component(str(part_path), 0.0, 0.0, 0.0),
    )
    await probe.step("save_assembly_as", lambda: adapter.save_file(str(asm_path)))

    # In-place save of the assembly after the part changed.
    await _modify_part(probe, adapter, part_path, 1)
    await probe.step(
        "activate_assembly", lambda: adapter.activate_document(str(asm_path))
    )
    part_before = _mtime(part_path)
    asm_before = _mtime(asm_path)
    await probe.step(
        "save_assembly_in_place (part modified)",
        lambda: adapter.save_file(None),
    )
    report["in_place_save"] = {
        "part_written": _mtime(part_path) != part_before,
        "assembly_written": _mtime(asm_path) != asm_before,
    }
    print(f"[probe] in-place save wrote: {report['in_place_save']}")

    # Close with save after the part changed again.
    await _modify_part(probe, adapter, part_path, 2)
    await probe.step(
        "activate_assembly_2", lambda: adapter.activate_document(str(asm_path))
    )
    part_before = _mtime(part_path)
    asm_before = _mtime(asm_path)
    await probe.step(
        "close_assembly_with_save (part modified)",
        lambda: adapter.close_model(save=True),
    )
    report["close_with_save"] = {
        "part_written": _mtime(part_path) != part_before,
        "assembly_written": _mtime(asm_path) != asm_before,
    }
    print(f"[probe] close with save wrote: {report['close_with_save']}")
    report["assembly_title"] = asm_title


async def run(mode: str) -> int:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT / f"{stamp}-{mode}"
    scratch = out / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"started": stamp, "mode": mode, "steps": []}

    adapter = PyWin32Adapter({})
    await adapter.connect()
    window = _frame_window(adapter)
    report["solidworks_pid"] = window.process_id()
    report["initial_state"] = window.state()
    print(
        f"[probe] SolidWorks pid {report['solidworks_pid']}, window {report['initial_state']}"
    )
    baseline = await _open_titles(adapter)
    report["documents_before"] = sorted(baseline)
    window.minimize()

    probe = Probe(adapter, window)
    try:
        if mode == "saves":
            await run_saves(adapter, probe, report, out, scratch)
        else:
            await run_full(adapter, probe, report, out, scratch)
    finally:
        report["steps"] = probe.steps
        # Close only what this run opened, never the user's documents.
        for title in set(await _open_titles(adapter)) - set(baseline):
            adapter._attempt(lambda t=title: adapter.swApp.CloseDoc(t))
        report["documents_after"] = sorted(await _open_titles(adapter))
        if report["initial_state"] in ("normal", "maximized"):
            window.restore()
        await adapter.disconnect()
        for path in scratch.glob("*"):
            try:
                path.unlink()
            except OSError:
                pass
        report_path = out / "report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[probe] report: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run("saves" if "--saves" in sys.argv else "full")))
