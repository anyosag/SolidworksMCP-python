## 1. Probe

- [x] 1.1 `adapters/solidworks/window.py`: `SolidWorksWindow` (Win32 only, injectable `user32`): `state`, `is_minimized`, `minimize`, `restore`, `foreground_is_solidworks`, `give_focus_to`, `give_focus_back(_soon)` (the planned `offscreen_restore()` was dropped after the probe); tests in `tests/solidworks_mcp/adapters/solidworks/test_window.py`
- [x] 1.2 `adapters/solidworks/dialogs.py`: find the modal dialogs of a process, read their title, visible texts (`WM_GETTEXT` for edit controls) and buttons, cancel one (task dialog, Cancel button, `WM_CLOSE`); self-dismissing dialogs get their countdown; the arm/disarm watchdog thread; tests in `test_dialogs.py`
- [x] 1.3 `tests/scripts/probe_minimized.py`: minimize, run the scratch part/assembly/save/screenshot/drawing/close sequence, record window state, foreground and dialogs after each step, check the screenshots for content; `--saves` mode for the save prompts and a `create_part` timeline. Results in design.md, "Probe results" (runs 1 and 2)

## 2. Keep minimized

- [x] 2.1 `connect()`: window handle from `Frame.GetHWnd`, `Visible = True` only when hidden, re-minimize and give focus back if connecting restored it; tests
- [x] 2.2 `_handle_com_operation`: outermost-call guard, focus remembered across operations and handed back (retried in the background), `SOLIDWORKS_MCP_KEEP_MINIMIZED`; tests in `tests/solidworks_mcp/adapters/test_pywin32_adapter_window_guard.py`
- [x] 2.3 ~~Re-minimize polling thread~~: not needed. The probe showed restores happen inside the call and stay (design.md D4)
- [x] 2.4 `mock_adapter.py`: simulated window state that `set_window_state` and `export_image` read; tests beside it

## 3. Screenshots while minimized

- [x] 3.1 `export_image`: no `Frame.SetFocus()` while minimized; `SaveBMP` as today (it renders while minimized); `window_state` in the result; tests
- [x] 3.2 `mock_adapter.py` `export_image` returns `window_state`; tests

## 4. Saves

- [x] 4.1 `adapters/solidworks/saving.py`: `save_document` (`Save3` / `SaveAs3` with by-ref out-params, `Silent` / `Silent | SaveReferenced`, error and warning names, no legacy `Save()` fallback) used by `save_file` and `close_model(save=True)`; tests in `test_saving.py`, existing save tests updated
- [x] 4.2 Export calls use `Silent | Copy` (3, `_EXPORT_OPTIONS`); tests
- [x] 4.3 Session registry of created and first-saved paths, reference classification, `NeedsConfirmation` -> `confirmation_required` (rule in `tools/error_classifier.py`; `data.files` always reaches the caller); tests
- [x] 4.4 `overwrite_modified_references` on the `save_file`, `save_assembly`, `save_as` and `close_model` inputs, through `base.py`, `connection_pool.py` and `circuit_breaker.py`; tool descriptions updated; tests
- [x] 4.5 `mock_adapter.py`: simulated modified user files (`_modified_user_files`) and the confirmation flow; tests

## 5. Dialog watchdog

- [x] 5.1 Arm the watchdog around the outermost operation; a cancelled dialog becomes an error result with `data.dialog` (`SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS`); tests
- [x] 5.2 `mock_adapter.py`: no watchdog (no window to watch); nothing to simulate beyond the error rule's tests
- [x] 5.3 The `solidworks_dialog` rule in `tools/error_classifier.py`; `data.dialog` always reaches the caller; tests

## 6. Window tool

- [x] 6.1 `set_window_state` in `base.py`, `pywin32_adapter.py`, `connection_pool.py`, `circuit_breaker.py` (not counted by the breaker); tests
- [x] 6.2 `mock_adapter.py` `set_window_state`; tests
- [x] 6.3 `set_solidworks_window` in `tools/server_admin.py`, `support_levels.py`, `tool_hints.py`; tests in `tests/solidworks_mcp/tools/test_server_admin.py`

## 7. Docs and ship

- [x] 7.1 CLAUDE.md runbook entries (minimized window; save prompts and the watchdog); `docs/agents/com-api-pitfalls.md` entries (save option values, Save Modified Documents, minimized rendering and focus); README settings; the agent skill (`references/errors-and-limits.md` done); CHANGELOG; `openspec/queue.md`
- [x] 7.2 Lint (`ruff check`, `ruff format --check`) and the mock suite: 3896 passed, 15 skipped, total coverage 99.3%, the new modules at 100%
- [x] 7.3a `tests/live/test_live_sw_keep_minimized.py` on SW 2026 SP4.1: 5/5 pass (stays minimized with the focus returned; minimized screenshot; assembly save of a session part without a dialog; confirmation before overwriting a user's part, then the confirmed save; a blocking "Cannot open" dialog cancelled and reported)
- [x] 7.3c After the keeper, dialog fix and foreground lock: 5/5 pass again. Foreground log in design.md: 18 grabs remain, so the lock is only a partial fix
- [x] 7.3d The rebuild prompt on activating a changed assembly: `activate_doc` activates with `swDontRebuildActiveDoc` (it passed `swUserDecision`) and then calls `EditRebuild3`; `swRebuildActiveDoc` showed a "Loading..." dialog instead; the preference-230 approach removed, since it had no effect (design.md D4d); tests in `test_io_activate_doc.py`. Live check 4: 5/5 pass, and SolidWorks takes the foreground only for the deliberate "Cannot open" dialog
- [x] 7.3b `test_live_sw_regression.py` minimized: 57 passed, 2 skipped; SolidWorks visible 12.2 s of 18.6 min, foreground taken only by interference detection's progress windows (design.md)
- [ ] 7.3e Sign off with `live-demo-signoff`
