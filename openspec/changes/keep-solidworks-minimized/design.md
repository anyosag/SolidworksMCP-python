## Context

The adapter drives one SolidWorks process over COM from the server's event-loop thread (CLAUDE.md, "COM threading architecture"). Every operation goes through `PyWin32Adapter._handle_com_operation`, which pauses after the call (`_settle_after`). That gives one place to act before and after each operation.

What earlier work ruled out:
- **A hidden window** (`SOLIDWORKS_MCP_HEADLESS`): sketch calls fail with `RPC_E_DISCONNECTED` (`tests/live/conftest.py`).
- **`DocumentVisible(False)`:** stops sketch creation (pitfall #26).
- **`CommandInProgress`:** made crashes come sooner (pitfall #26).

So the window has to stay shown, and minimized is the state to keep.

Constants checked in `swconst.tlb` (SW 2026):

| Enum | Values |
|---|---|
| `swWindowState_e` | Normal = 0, Maximized = 1, Minimized = 2 |
| `swSaveAsOptions_e` | Silent = 1, Copy = 2, SaveReferenced = 4 |
| `swFileSaveError_e` | includes `swFileSaveRequiresSavingReferences` = 8192 |

## Goals / Non-Goals

**Goals:**
- A minimized SolidWorks stays minimized while tools run, and doesn't take keyboard focus.
- Screenshots work while minimized.
- Assembly saves don't show the Save Modified Documents dialog.
- Nothing overwrites the user's existing files without their confirmation.
- A stray modal dialog can't hang the server.

**Non-Goals:**
- Running SolidWorks hidden or headless.
- Driving several SolidWorks instances.
- Answering save prompts with Save or Don't Save automatically.
- The "save before inserting" and "save before drawing" prompts (not reported yet; the watchdog covers them as a safety net).

## Decisions

### D1. The window is handled with Win32 calls only, in `adapters/solidworks/window.py`

`SolidWorksWindow(hwnd, user32=None)` wraps `IsIconic`, `IsWindowVisible`, `ShowWindow`, `GetForegroundWindow`, `GetWindowThreadProcessId`, `GetWindowPlacement` / `SetWindowPlacement`. It uses ctypes and makes no COM calls, so it can run on any thread without breaking the STA rule. Tests pass a fake `user32`, the same pattern as `registry=` in `setup/solidworks.py`.

**Alternative rejected:** `ISldWorks.FrameState`. It is COM, so it is bound to the connect thread, and it can't minimize without activating the window.

### D2. The window handle comes from the connected instance

`connect()` reads `swApp.Frame` → `IFrame.GetHWnd()`, through `_get_attr_or_call`, and stores it. A process lookup could pick another SolidWorks: two were running on the user's machine.

### D3. Sticky minimized state lives in `_handle_com_operation`

- **Depth counter:** only the outermost call acts, so nested operations don't act twice.
- **Before the call:** record `was_minimized`.
- **In `finally`, after `_settle_after`:** if it was minimized and isn't now, minimize it again.
  - With `SW_MINIMIZE` when SolidWorks owns the foreground, so Windows gives focus to the next window, usually the user's.
  - With `SW_SHOWMINNOACTIVE` otherwise.
- **`connect()`** does the same around its own sequence, and sets `Visible = True` only when the window isn't visible.
- **Setting:** `SOLIDWORKS_MCP_KEEP_MINIMIZED` (default on) turns this off.

### D4b. A keeper thread remembers the wish (replaces D4's "no polling thread")

The first live regression run (2026-11-10) showed the operation guard alone isn't enough. SolidWorks came up 6 s in, through a COM call outside `_handle_com_operation` (the suite's document drain), and stayed up for the rest of the run, about 169 of 175 s. It also had the focus for about 40 s. Every later operation then saw a visible window and took it for one the user had restored.

`MinimizeKeeper` (in `window.py`, one per window per process, shared by every adapter) now:
- **remembers the wish:** set when an operation starts with the window minimized, or by `set_solidworks_window minimize`; cleared by `restore`;
- **watches the window** every 0.15 s from its own Win32-only thread:
  - if SolidWorks comes up while an operation runs, or within 2 s of any COM activity (`_attempt` counts), it minimizes it again with `ShowWindowAsync` and hands the focus back;
  - if SolidWorks comes up while idle, the user restored it, so the wish is dropped.

The end-of-operation guard (D3) stays as the immediate backstop, and also acts when the wish is set even if the operation started with the window up.

**Accepted risk:** if the user restores SolidWorks during an operation, or within 2 s of one, it is minimized again once. Restoring it again works.

### D4c. Lock the foreground during operations; never hide a dialog

- **Live check 2 (2026-11-10), 4/5 passed.**
  - The blocking-dialog test failed: the keeper minimized SolidWorks while its "Cannot open" box was up. A minimized owner hides its dialogs, so the watchdog (which looks for visible dialogs) never saw it, and the call blocked for 221 s.
  - Fix: while the frame is disabled (a modal dialog is up), the keeper and the end-of-operation guard leave the window up. A dialog that appears while SolidWorks is minimized is shown with `SW_SHOWNOACTIVATE`.
- **The user's Stage Manager switched to SolidWorks and straight back** whenever SolidWorks took the foreground for an instant. It acts on `EVENT_SYSTEM_FOREGROUND`, so handing the focus back afterwards is too late.
  - First try, `LockSetForegroundWindow` held for each operation: no effect. Probe 1 created 6 parts; every one grabbed the foreground (52–155 ms), lock or not. Windows' foreground lock timeout on this machine is at its maximum, and the user had been idle 47 minutes, so neither explains the grab.
  - Probe 2: `WS_EX_NOACTIVATE` on the frame during `create_part` gave 0 grabs in 2 of 2. Creating the document hidden (`DocumentVisible(False)`) and showing it while minimized still grabbed (21–52 ms), though sketches and extrusions worked on such a document.
  - Fix: each operation that starts with SolidWorks meant to stay minimized, while the user is in another program, adds `WS_EX_NOACTIVATE` to the frame and removes it when the operation ends. Connect and disconnect remove any left by a server that died mid-call. `SOLIDWORKS_MCP_BLOCK_ACTIVATION=0` turns it off.
  - Cost: during the operation the user can't click SolidWorks up. SolidWorks' own dialogs are separate windows and can still take the foreground.
- **Focus to the user's window, not the next in Z-order:** `minimize(focus_to=...)` uses `SW_SHOWMINNOACTIVE` and hands the focus straight back. `SW_MINIMIZE` sometimes gave it to the desktop, which a window manager also acts on.

**Live check 3** (keeper, dialog fix and lock), 5/5 passed. A logger of `EVENT_SYSTEM_FOREGROUND` and minimize/restore events ran through it:
- SolidWorks was restored 20 times and every time minimized again, mostly within 0.1–0.2 s. About 12 of those restores came without taking the foreground.
- It still took the foreground 18 times:
  - 6 were short blips (20–170 ms) while creating documents;
  - 3 were its own dialogs ("Dialog", "Loading...", the "Cannot open" box), each held for ~10 s;
  - the rest came at test-fixture boundaries.
- Twice the focus went to the desktop ("Program Manager") rather than back to Claude.
- So the lock helps, but doesn't stop every grab. Likely cause: COM passes the client's foreground permission to the server on each call, and SolidWorks activates itself with it.

### D4d. Don't let calls open dialogs: activate without the rebuild prompt

After D4c the grabs left came from SolidWorks' own dialogs, mainly the rebuild prompt when an assembly whose part changed is activated (the live save tests showed "Dialog", then "Loading...", each time). A dialog is its own window, so `WS_EX_NOACTIVATE` on the frame doesn't stop it.

Probes on a scratch part and assembly (2026-11-10):

| Attempt | Prompt |
|---|---|
| Set the user preference `swRebuildOnActivation` (230) to 2, put back at once | shown, 0.4 s |
| The same, held for 5 s | shown, 0.3 s |
| `ForceRebuild3` on the assembly before activating it | shown, 0.3 s |
| `ActivateDoc3(title, False, 2, errors)` (`swRebuildActiveDoc`) | **none**; afterwards `NeedsRebuild2` = 0 |
| `ActivateDoc3(title, False, 1, errors)` (`swDontRebuildActiveDoc`) | **none**; afterwards `NeedsRebuild2` = 1 |
| `ActivateDoc3(title, False, 0, errors)`, as every call passed | shown, 0.2 s; after it dismissed itself, `NeedsRebuild2` = 0 |

With `UseUserPreferences` false, `ActivateDoc3`'s `Option` decides, and `0` is `swUserDecision`: the code asked for the prompt itself.

Option `2` wasn't enough. The live assembly tests, run with a foreground logger, still showed SolidWorks taking the foreground once per activation, through a "Loading..." window. A probe that hooked foreground events and timestamped each call showed it was a `#32770` progress dialog owned by the frame. It came up during `ActivateDoc3` with option `2`, took the foreground for about 0.5 s, and once handed it to the desktop. Rebuilding after the activation instead shows nothing:

| Activation | Foreground / restore | `NeedsRebuild2` after |
|---|---|---|
| Option `2` | "Loading...", the frame, then the desktop; restored | 0 |
| Option `1`, then `ForceRebuild3(False)` | none | 0 |
| Option `1`, nothing more | none | 1 |
| `activate_document` with the new `activate_doc` (option `1`, then `EditRebuild3`), twice | none | 0 both times |

So `activate_doc` activates with option `1`, then calls `EditRebuild3`, which rebuilds only what changed, unless `NeedsRebuild2` is 0. The assembly is up to date for the calls that follow, as the box's default answer would leave it. The user's preference isn't touched.

**Live check 4** (all five keep-minimized tests, with the foreground logger), 5/5 passed:
- SolidWorks took the foreground twice. Both were in the blocking-dialog test, which opens the "Cannot open" box on purpose; after the box was cancelled the focus went to the desktop rather than back to Claude.
- It was restored 7 times, by `NewDocument` (`create_part`, `create_assembly`). Each time it was minimized again within 0.12 s, with no foreground change.
- For comparison: the assembly tests alone gave 8 grabs before D4d, and the full run gave 18 after D4c.

**Live regression suite, minimized** (`test_live_sw_regression.py`, 2026-11-10, with the foreground logger, `SW_TEST_PACE_SECONDS=0`): 57 passed, 2 skipped (they need a test part path), in 18.6 min.
- SolidWorks was restored 60 times, each by a document call, and minimized again every time. It was visible for 12.2 s in all, never more than 0.51 s at once. The first regression run, before D4b, had it up for about 169 of 175 s.
- It took the foreground 6 times, all in `test_check_interference_answers_both_ways`. `IInterferenceDetectionMgr` shows SolidWorks' own "Loading..." and "Calculating Interference Detection" progress windows, and the frame follows each. The focus then went back to the user's window.
- No `RPC_E_DISCONNECTED` or other flakes: running minimized didn't bring back the failures of the hidden mode (Risks, "Minimized rendering").

### D4. No polling thread; give the focus back (superseded in part by D4b)

The probe showed the restores happen inside the call and stay, never later. So minimizing once after the call (D3) is enough, and no polling thread is added: re-minimizing while SolidWorks is still inside `NewDocument` would make it lay its UI out again mid-call, the idle-time work pitfall #26 crashed in.

SolidWorks keeps the foreground after it is minimized again, so the guard also records the foreground window when a call starts minimized and hands the focus back to it afterwards (`give_focus_to`: `AttachThreadInput` to the foreground thread, then `SetForegroundWindow`).

### D5. Screenshots: `SaveBMP` while minimized

The probe showed `SaveBMP` renders correctly while minimized (see "Probe results"), so `export_image` keeps its current path. `Frame.SetFocus()` is skipped while minimized, and the result reports `window_state`.

**Dropped:** the off-screen restore and alpha-0 fallbacks planned here. They aren't needed, and `SetWindowPlacement` moves an off-screen window back on screen anyway.

### D6. One save helper with real out-parameters

- **Out-parameters:** `Save3(options, errors, warnings)` and `IModelDocExtension.SaveAs3(...)` get by-ref `VT_I4` VARIANTs (`_byref_long` / `_byref_int`). Passing `None`, as today, fails under late binding, so the code falls back to the dialog-prone `Save()`.
- **Options:** `Silent` for parts and drawings; `Silent | SaveReferenced` for an assembly once its references are cleared (D7).
- **Errors and warnings** are decoded into names.
- **Exports** use `Silent | Copy` (3) in place of 2.
- **Callers:** `save_file`, Save As and `close_model(save=True)` all use the helper.

### D7. Classifying modified references

- **Session registry:** the adapter keeps a set of normalized paths it created or saved for the first time this session.
- **Before an assembly save,** it walks `IAssemblyDoc.GetComponents(False)` → `IComponent2.GetModelDoc2()` and collects the documents whose `GetSaveFlag()` is true, without duplicates.
- **Each one is:**
  - *new*: no path, a virtual component, or in the registry
  - *existing*: anything else
- **If any are existing** and `overwrite_modified_references` is false, it raises `ConfirmationRequiredError` before writing anything. The tool boundary maps that to `confirmation_required` (a new rule in `tools/error_classifier.py`).
- **Otherwise** it saves with `Silent | SaveReferenced`.

### D8. The dialog watchdog cancels, nothing more

- **Where and when:** `adapters/solidworks/dialogs.py`, a Win32-only thread, armed by the outermost `_handle_com_operation` call and disarmed in its `finally`.
- **What counts as a dialog:** a visible, enabled top-level window of the connected SolidWorks process, with class `#32770`, whose owner is the frame and while the frame is disabled (that is, modal).
- **After the timeout,** it records the title, the static texts and the button captions, then cancels:
  - `TDM_CLICK_BUTTON(IDCANCEL)` for a task dialog
  - `BM_CLICK` on the Cancel button
  - `WM_CLOSE` if there's no Cancel button
- **Then** the COM call returns, and `_handle_com_operation` turns the recorded dialog into a `SolidWorksDialogError`, mapped to `solidworks_dialog`.
- **It never presses** Save, Don't Save, Yes or No.

### D9. The window tool goes through the adapter

`set_window_state(state)` is added to `adapters/base.py` and forwarded by `connection_pool.py` and `circuit_breaker.py`, like `reset_circuit_breakers`. `mock_adapter.py` simulates the state. The tool is `set_solidworks_window` in `tools/server_admin.py`.

## Risks / Trade-offs

- **[Minimized rendering]** SolidWorks may skip work for a 0×0 graphics area. → The probe and the minimized run of `test_live_sw_regression.py` check for the `RPC_E_DISCONNECTED` flakes the hidden mode had. If they appear, the guard falls back to keeping the window at its normal size off-screen.
- **[Off-screen clamping]** SolidWorks or Windows may move an off-screen window back on screen. → The probe checks `GetWindowRect` after the restore; the alpha-0 method is the fallback.
- **[Watchdog false positives]** A legitimate modal that takes longer than the timeout would be cancelled. → Cancel is always the safe choice, the text is returned so the agent can retry, and the timeout can be changed.
- **[`GetSaveFlag` accuracy]** A referenced document may be dirty without its flag set. → The save also checks for `swFileSaveRequiresSavingReferences` (8192) from a `Silent`-only first attempt, and treats that as "references need saving".

## Probe results

Run 1 (2026-11-10, SOLIDWORKS 2026 SP4.1 Student, `probe_minimized.py`, before any change):

| Step | Window after the call | SolidWorks took the focus |
|---|---|---|
| Reconnect (`Visible = True`) while minimized | minimized | no |
| `create_part` (`NewDocument`) | **restored** | **yes** |
| Sketch, rectangle, extrude, save part | minimized | no |
| `export_image` | minimized | no |
| `create_assembly` (`NewDocument`) | **restored** | **yes** |
| `insert_component`, activate part, part edits | minimized | kept it |
| Activate the assembly | **restored**, with a dialog | yes |
| Save the assembly under a new name (part modified) | minimized, **no dialog** | kept it |
| `create_drawing`, `close_model` | minimized | kept it |
| `close_model(save=False)` on a modified part | minimized, **no prompt** | kept it |

What it showed:

- **Restores happen inside the call and stay:** the window was already restored when the call returned, and still restored 1.5 s later. So minimizing again after the call is enough, and a polling thread isn't needed (D4). The window is visible while the call runs.
- **SolidWorks keeps the foreground once it has it,** even after it is minimized again. `SW_MINIMIZE` didn't always pass the focus on. So the guard also gives the focus back to the window that had it when the call started (`SolidWorksWindow.give_focus_to`, using `AttachThreadInput` + `SetForegroundWindow`).
- **Screenshots work while minimized.**
  - `export_image` wrote a correct 800×600 isometric image without restoring the window.
  - A raw `SaveBMP` while minimized gave a non-blank image. The graphics area keeps its last size (565×405) while minimized.
  - So D5's off-screen restore isn't needed. It doesn't work anyway: `SetWindowPlacement` moves a fully off-screen rectangle back on screen, and the window came up on the monitor.
- **The dialog when activating the assembly** was a SolidWorks message box titled "(Automatically dismissing in 5 seconds)" with placeholder developer text. It carries every button (OK, Cancel, Yes, No, Abort, ...) and shows only some, so the watchdog now reads only visible controls. It cancelled the dialog.
- **Saving an assembly under a new name didn't show "Save Modified Documents".** Run 2 (`--saves`) checks an in-place save and `close_model(save=True)`.
- **`CloseDoc` doesn't prompt** for a modified document.

Run 2 (`--saves`, with the guard and watchdog already in the adapter):

- **The "Save Modified Documents" case, reproduced.** A part was changed after the assembly was saved, then:

  | Call | What SolidWorks did | Files written |
  |---|---|---|
  | Save the assembly in place (`Save3(1, None, None)`, falling back to `Save()`) | showed a "SOLIDWORKS Design" dialog | neither file |
  | `close_model(save=True)` (`Save`) | showed the same dialog | neither file |

  The watchdog cancelled both after 5 s, so nothing was overwritten. D6 and D7 replace these paths with a silent save.
- **Timeline of `create_part`, polled every 20 ms:**

  | Time | Window | Focus |
  |---|---|---|
  | 0.73 s | restored, inside `NewDocument` | the user's app |
  | 1.46 s | minimized again by the guard, at the end of that operation | SolidWorks kept it |
  | 6.3 s | minimized | back with the user's app |

  The tool runs several operations, so `_focus_to_return` now remembers the user's window across operations. The hand-back also retries in the background (`give_focus_back_soon`) when SolidWorks is too busy to let go.
- **Activating an assembly whose part changed** shows SolidWorks' "(Automatically dismissing in 5 seconds)" message box each time. The watchdog cancelled it at 5 s, racing the box's own countdown, and turned a successful activation into an error. Dialogs whose title announces a countdown now get the countdown plus 2 s (`patience_for`).
- **Live test run 1** (`tests/live/test_live_sw_keep_minimized.py`):
  - Passed: staying minimized and getting the focus back across part, assembly and save calls; an 800×600 screenshot with real content while minimized.
  - Failed: activating the assembly. The self-dismissing box ("Models contained within the assembly have changed. Would you like to rebuild the assembly now?", Yes / No) got its countdown into the title only after the watchdog first saw it, so it was cancelled at 5 s.
  - Fix: the watchdog re-reads the title on every poll, and leaves a counting-down box alone until its countdown plus 2 s, at most 30 s.
- **The save dialog's text** wasn't in `#32770` static controls: only the title was read. Text controls of another process are now read with `WM_GETTEXT` (`SendMessageTimeoutW`, 200 ms), since `GetWindowText` only returns captions.

## Open Questions

- Does `CloseDoc` prompt for a modified document? The probe records it.
- Which screenshot method works on SW 2026 SP4.1?
- Is the polling thread needed?
