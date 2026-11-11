## Why

A user wants to minimize SolidWorks and keep working in other apps while an agent drives it through this server. Today that doesn't hold:

- `connect()` sets `app.Visible = True` on every connect (`pywin32_adapter.py`). Document calls (`NewDocument`, `OpenDoc6`, `ActivateDoc3`) may also restore a minimized window and take keyboard focus. Nothing records or restores the window's state.
- `export_image` calls `Frame.SetFocus()` and renders with `SaveBMP` at the size of the window's graphics area. A minimized window's graphics area is 0×0.
- Saving an assembly whose parts changed shows SolidWorks' modal "Save Modified Documents" dialog, which blocks the COM thread with no timeout. The save paths aren't silent:
  - `Save3(1, None, None)` can't marshal its by-ref out-parameters under late binding, so it falls back to the legacy `Save()`.
  - `SaveAs3(path, 0, 0)` passes no options.
  - `close_model(save=True)` calls `Save`.
  - The export calls pass `2` as "Silent", but the SW 2026 constants type library says `swSaveAsOptions_Silent = 1` and `swSaveAsOptions_Copy = 2`.

No GitHub issue (work on the fork `anyosag/SolidworksMCP-python`).

## What Changes

- **Sticky minimized state.** If SolidWorks is minimized when an operation starts, the adapter keeps it minimized through that operation and hands focus back to the user's window. If the user restores it, it stays up. `connect()` shows the window only when it is actually hidden. `SOLIDWORKS_MCP_KEEP_MINIMIZED=0` turns this off.
- **Screenshots while minimized.** `export_image` no longer takes focus. It renders while minimized, or briefly restores the window off-screen without activating it, then minimizes it again. The result reports `window_state`.
- **Silent saves.** Saves go through one helper using `Save3` / `SaveAs3` with `Silent` (and `SaveReferenced` for assemblies) and real by-ref out-parameters. It reports `swFileSaveError_e` / `swFileSaveWarning_e`. The export calls switch to `Silent | Copy`.
- **Overwrite confirmation.** Before an assembly save writes modified referenced files, the adapter classifies them:
  - never saved, or created or first saved by this server session → saved automatically
  - modified existing files of the user's → the save stops, writes nothing, and returns `error_type: confirmation_required` listing them

  The save tools (`save_file`, `save_assembly`, `save_as`, `close_model`) gain `overwrite_modified_references` (default false).
- **Dialog watchdog.** While an operation runs, a Win32-only thread watches for modal dialogs of the connected SolidWorks process. After `SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS` (default 5; 0 off) it records the dialog's text and presses Cancel (never Save or Don't Save). The operation then returns `error_type: solidworks_dialog` instead of hanging.
- **New tool** `set_solidworks_window` (`minimize` | `restore`), returning the window state.

## Capabilities

### New Capabilities
- `adapters/solidworks-window`: the window's minimized state across operations, minimized screenshots, and the window tool.
- `adapters/save-prompts`: silent saves, overwrite confirmation for assemblies, and the dialog watchdog.

### Modified Capabilities

## Impact

- **COM/adapter code (extra risk per CLAUDE.md):** `pywin32_adapter.py` (`connect`, `_handle_com_operation`, `export_image`, export save options), `adapters/solidworks/io.py` (save paths, `close_model`), `adapters/base.py`, `mock_adapter.py`, `connection_pool.py`, `circuit_breaker.py`.
- **COM threading:** the new window and dialog modules use only Win32 calls (no COM), so the polling threads don't break the STA rule. Every COM call stays on the connect thread.
- **New modules:** `adapters/solidworks/window.py`, `adapters/solidworks/dialogs.py`; a tool in `tools/server_admin.py`.
- **Other changes:** error rules in `tools/error_classifier.py`; tool schemas for the save tools; `support_levels.py`, `tool_hints.py`; CLAUDE.md runbook, `docs/agents/com-api-pitfalls.md`, README, agent skill.
- **Tests:** beside each module; a live probe script `tests/scripts/probe_minimized.py`; a live test `tests/live/test_live_sw_keep_minimized.py`.
