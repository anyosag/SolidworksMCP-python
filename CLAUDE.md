# SolidWorks MCP Server (Python)

This file is the quick orientation guide for contributors and coding agents.

## Platform and Runtime

- Primary runtime is Python 3.13+.
- Real COM automation requires Windows + SolidWorks installed.
- Cross-platform development is possible in mock/test mode.

## Build and Development Commands

Use either micromamba environment commands or local virtualenv commands.

### Preferred PowerShell workflow

```powershell
# Show command help
.\dev-commands.ps1

# Full install in micromamba env
.\dev-commands.ps1 dev-install

# Fast test pass (no SolidWorks-required tests)
.\dev-commands.ps1 dev-test

# Full test run including real SolidWorks integration
.\dev-commands.ps1 dev-test-full

# Lint and format
.\dev-commands.ps1 dev-lint
.\dev-commands.ps1 dev-format

# Docs build/serve
.\dev-commands.ps1 dev-docs-build
.\dev-commands.ps1 dev-docs-strict
.\dev-commands.ps1 dev-docs-audit
.\dev-commands.ps1 dev-docs
```

### Virtualenv direct workflow

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -e ".[dev,test,docs]"

# Run server
.\.venv\Scripts\python.exe -m solidworks_mcp.server

# Lint/tests/docs
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest tests -m "not solidworks_only"
.\.venv\Scripts\python.exe -m mkdocs build --clean
```

## Architecture

- Server entrypoint: `src/solidworks_mcp/server.py`
- CLI entrypoint: `src/solidworks_mcp/server_cli_fixed.py`
- Adapters: `src/solidworks_mcp/adapters/`
  - `pywin32_adapter.py`: real SolidWorks COM adapter (Windows)
  - `mock_adapter.py`: mock adapter for tests and CI-like runs
  - `factory.py`: adapter selection/routing logic
- Tools: `src/solidworks_mcp/tools/` (modeling, sketching, drawing, export, analysis, automation, templates, VBA, docs discovery)
- Agent harness: `src/solidworks_mcp/agents/` (prompt schemas, smoke test CLI, run/error persistence)

## Key Patterns

### COM and Adapter Safety

- Prefer adapter abstraction, not direct COM calls from tool modules.
- Keep Windows/COM behavior behind adapter boundaries.
- Use mock adapter for tests unless a test explicitly requires real SolidWorks.

### Logging and Output

- Use project logging utilities (`loguru`/configured helpers).
- Avoid ad-hoc print statements in runtime server paths.

### Validation and Tool Contracts

- Keep tool input schemas strict and explicit.
- Maintain stable response payload shapes (`status`, `message`, `execution_time`, plus data payload).
- Every tool runs inside one error boundary (`tools/tool_boundary.py`, applied
  by `ToolRegistrar` at registration). Do **not** write `try/except` in a tool
  or build error dicts by hand:
  - adapter results: `require_success(result, context="Failed to ...")`
  - bad arguments: `normalize_input(...)` or raise `InvalidInputError`
  - a missing capability: `require_capability(adapter, "method")`
  - any other tool-level failure: raise `ToolOperationError(message)`
- Error payloads always carry `status: "error"`, `message`, `error_type`,
  `hint` and `execution_time` (`data` only when the adapter returned
  diagnostics). `error_type` comes from the ordered rule table in
  `tools/error_classifier.py`; add a category by appending a rule there.

## Testing Guidance

- Default local path: run non-`solidworks_only` tests first.
- Real integration path: run `dev-test-full` on Windows with SolidWorks available.
- Harness and generated report artifacts may write under `tests/.generated/` and `.solidworks_mcp/`.
- Test layout mirrors `src/` (enforced by `tests/integration/test_test_layout.py`):
  - `src/solidworks_mcp/<path>/<module>.py` →
    `tests/solidworks_mcp/<path>/test_<module>[_<topic>].py`
  - a package's `__init__.py` → `test_init.py`
  - cross-module / end-to-end tests → `tests/integration/`
  - real-SolidWorks tests → `tests/live/`
  - never add "coverage bucket" files (`test_coverage_*.py`); put each test
    beside the module it exercises
- Coverage is measured honestly: there is no `# pragma: no cover`. Code no
  test can reach is deleted, after review, via the dead-code ledger
  (`openspec/changes/archive/2026-10-30-full-coverage-and-error-boundary/dead-code.md`).

## Documentation Guidance

- Build docs before commit when touching docs pages:
  - `.\dev-commands.ps1 dev-docs-build`
  - `.\dev-commands.ps1 dev-docs-strict`
- For local preview:
  - `.\dev-commands.ps1 dev-docs`

## Agent and Model Notes

- VS Code Copilot subscription is suitable for chat-based workflows.
- Local Python smoke tests require explicit provider credentials:
  - GitHub Models: `GH_TOKEN` or `GITHUB_API_KEY`
  - OpenAI: `OPENAI_API_KEY`
  - Anthropic: `ANTHROPIC_API_KEY`

## Troubleshooting Runbook

When the bridge misbehaves, walk this list in order. Compiled from SolidWorks
forum threads, pywin32 issues, and observed failures on this install. Last
updated 2026-04-24.

### 1. `OpenDoc6` HRESULT failure — pass-by-ref params

- **Cause:** pywin32 `makepy`/`gencache` marks SW's pass-by-ref `errors` and
  `warnings` parameters as non-optional inputs. Calls fail unless
  `pythoncom.Missing` is passed explicitly.
- **Check:** grep server code for `OpenDoc6(`; every callsite should pass
  `pythoncom.Missing` for the last two params.
- **Fix:**
  `model, errors, warnings = sw.OpenDoc6(path, type, opts, '', pythoncom.Missing, pythoncom.Missing)`
- **Error codes:** warning=128 = already open (not fatal); error=1024 = generic
  open failure. S_OK with null return is also possible.

### 2. `Member not found` / `NoneType not callable` — stale gencache

- **Cause:** pywin32 caches SW type-library wrappers under `%TEMP%\gen_py\`.
  SW upgrades (e.g. 2024 → 2025) or patches leave wrappers pointing at the
  old TLB.
- **Fix:** delete `%TEMP%\gen_py\`, restart the MCP server. Rebuilds on first
  call.

### 3. `solidworks_reconnected`, or every call failing after SolidWorks restarted — stale COM handle

- **Cause:** MCP server process grabbed a COM pointer at connect; user has
  since quit and reopened SolidWorks (or it crashed). Pointer is dangling:
  calls on it fail with `RPC_S_SERVER_UNAVAILABLE`.
- **Expected:** the server reconnects by itself. Before each call,
  `_handle_com_operation` checks, through Win32 only, that the frame window
  of the SolidWorks it connected to still exists and belongs to the same
  process; without a window handle, a failed call reads `RevisionNumber`
  and looks for an RPC error. If SolidWorks has exited, the server binds to
  the running SolidWorks with `GetActiveObject` (never `Dispatch`, which
  would start one). That call returns `solidworks_reconnected` without
  running, and the next call works. Documents from before are gone. With no
  SolidWorks running, calls return `solidworks_unavailable` until the user
  starts it.
- **If it still fails:** compare MCP server start time (Claude `main.log` →
  `Launching MCP Server: solidworks`) to current `SLDWORKS.exe` start time,
  and restart Claude Desktop (respawns MCP server, which grabs a fresh SW
  handle).

### 4. `Circuit breaker is open for <tool>`

- **Cause:** the server's circuit breaker pauses an operation after 5
  failures. Subsequent calls fail fast even when the underlying issue is
  fixed. Before #208 a single failure could count many times: the server's
  router fell back to the VBA adapter, which re-entered the router.
- **Fix:** call the `reset_circuit_breaker` tool (all operations, or one by
  name), or wait for the timeout (`SOLIDWORKS_MCP_CIRCUIT_BREAKER_TIMEOUT`,
  default 60 s), or restart the server.

### 5. COM apartment / threading mismatch — FastMCP async workers

- **Cause:** SolidWorks COM is STA (single-threaded apartment). An IDispatch
  proxy obtained on thread A cannot be invoked from thread B. FastMCP runs
  tool handlers on worker threads distinct from where `connect()` ran.
- **Signature (critical):** pywin32 late-binding surfaces this as
  ``AttributeError: SldWorks.Application.<method>`` at attribute lookup —
  **NOT** as ``pywintypes.com_error``. The `except com_error` branch in
  ``_handle_com_operation`` therefore misses it, and the generic handler
  flattens the message to the source+method name with no traceback.
- **Fix:** keep every COM call on the thread that ran `connect()`. See
  "COM threading architecture" below. (History: a dedicated `ComExecutor`
  thread was used from 2026-04-24; the adapter no longer routes through it,
  and `ComExecutor` now only serves standalone scripts.)

### 6. PDM vault files

- **Cause:** `OpenDoc6` on a file under a PDM working folder fails when the
  file isn't checked out or cached locally.
- **Check:** target path has PDM vault metadata / is under a PDM working
  folder.
- **Fix:** check the file out in PDM, or test with a copy outside the vault.

### 7. Silent-mode UI leak

- `swOpenDocOptions_Silent` still pops the UI on some SW-2025 SP levels.
  Cosmetic only; not a failure.

### 8. SW 2025 SP0 drawing crashes

- SP0 has reported `.slddrw` open crashes. If the target is a drawing,
  suggest upgrading to SP1+.

### 9. MCP log silence

- FastMCP banner output (emoji-prefixed lines to stdout) is misparsed as
  JSON-RPC by the Claude host — noise, not errors.
- Actual tool-call tracebacks go to **stderr** and are NOT captured in
  `%APPDATA%\Claude\logs\mcp-server-solidworks.log`. Check the
  `%LOCALAPPDATA%\solidworks_mcp\logs\` directory and the FastMCP install
  dir for a separate Python log.

### 10. Claude Code `settings.json` UTF-8 BOM (host-side, not SW)

- A BOM on `~/.claude/settings.json` makes Claude Code silently drop **all**
  user settings (`[SettingsIo] Failed to read ... Unexpected token '﻿'`).
  Strip the BOM; write plain UTF-8.

### 11. `SelectByID2` Callout type mismatch — use `VT_DISPATCH` null, not `None`

- **Signature:** `(-2147352571, 'Type mismatch.', None, 8)` on any `SelectByID2` call.
- **Cause:** The `Callout` parameter (8th arg) is typed `VT_DISPATCH`. Python `None`
  marshals as `VT_NULL` which SW rejects. Must pass an explicit COM null pointer:

  ```python
  import pythoncom, win32com.client as _win32com
  null_callout = _win32com.VARIANT(pythoncom.VT_DISPATCH, None)
  model.Extension.SelectByID2("", "EDGE", x, y, z, append, mark, null_callout, 0)
  ```

- **Applies to:** Every `SelectByID2` / `SelectByID` call with no real callout.

### 12. `InsertFeatureChamfer` is on `IFeatureManager`, not `IModelDocExtension`

- **Signature:** `<unknown>.InsertFeatureChamfer` when calling via `model.Extension`.
- **Cause:** `InsertFeatureChamfer` (DISPID 83) is on `IFeatureManager`.
  Routing through `model.Extension` (IModelDocExtension) causes `DISP_E_MEMBERNOTFOUND`.
- **Fix:** `fm = model.FeatureManager; fm.InsertFeatureChamfer(1, 1, width_m, pi/4, 0, 0, 0, 0)`
- **More detail:** See `docs/agents/com-api-pitfalls.md` for the full pattern catalogue.

### 13. `ForceRebuild3(True)` required before coordinate-based edge/face selection

- **Signature:** `SelectByID2("", "EDGE", x, y, z, ...)` returns `False` on a freshly
  created feature.
- **Cause:** New feature edges are not tessellated until an explicit rebuild.
  `SelectByID2` uses the tessellated mesh to resolve coordinates.
- **Fix:** Call `model.ForceRebuild3(True)` once before the first `SelectByID2` in a
  feature operation.

### 14. SolidWorks pops up while minimized, or takes the keyboard focus

- **Expected:** once SolidWorks is minimized (by the user, or by
  `set_solidworks_window`), the server keeps it minimized and gives the focus
  back to the user's window. `MinimizeKeeper` (`adapters/solidworks/window.py`)
  watches from its own thread: a restore during a call, or within 2 s of one,
  is undone at once; a restore while idle is the user's and is left alone.
  `create_part`, `create_assembly` and activating an assembly restore it
  during the call. To stop SolidWorks taking the foreground even for an
  instant (window managers such as a "Stage Manager" switch on
  `EVENT_SYSTEM_FOREGROUND`), each operation that starts minimized puts
  `WS_EX_NOACTIVATE` on SolidWorks' frame until it ends, and connect and
  disconnect clear any left behind (`SOLIDWORKS_MCP_BLOCK_ACTIVATION=0` turns
  that off; `LockSetForegroundWindow` was tried and doesn't stop it). While
  SolidWorks shows a modal dialog the keeper leaves it up, so the dialog
  watchdog can see and cancel it. Dialogs are separate windows and can still
  take the foreground, so don't let a call open one: activate documents
  through `io.activate_doc`, which activates with `swDontRebuildActiveDoc`
  and then calls `EditRebuild3` (for a changed assembly, `ActivateDoc3`
  option `0` shows a rebuild prompt and option `2` a "Loading..." dialog).
- **If SolidWorks won't come up when clicked:** a server that died mid-call
  may have left `WS_EX_NOACTIVATE` on the frame. Restart the server (connect
  clears it) or call `set_solidworks_window restore`.
- **Check:** `SOLIDWORKS_MCP_KEEP_MINIMIZED` isn't `0`; the server connected
  to the SolidWorks you minimized (it binds to the window of the instance it
  connected to, through `IFrame.GetHWnd`, so with two SolidWorks running it can
  be the other one).
- **Agents:** `set_solidworks_window` minimizes or restores it.

### 15. A tool returns `solidworks_dialog` or `confirmation_required`

- **`solidworks_dialog`:** SolidWorks opened a modal dialog during the call.
  The watchdog (`adapters/solidworks/dialogs.py`) cancelled it after
  `SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS` (default 5; `0` turns it off); its
  text is in `data.dialog`. It only presses Cancel or closes the dialog, never
  Save or Don't Save. A dialog it can't cancel brings SolidWorks up for the user
  to answer. Find what opened the dialog and make that call silent.
- **`confirmation_required`:** saving an assembly would overwrite the user's
  own modified part files (`data.files`); nothing was written. Call again with
  `overwrite_modified_references: true` once the user agrees. Saves are always
  silent (`adapters/solidworks/saving.py`; pitfalls #36 and #37).

### 16. A tool returns `active_document_changed`

- **Cause:** the user, or another program driving the same SolidWorks
  (another MCP client, a live test from another session), activated a
  different document since this session's last call. Some tools act on
  SolidWorks' active document, so the call would have changed theirs.
  `_handle_com_operation` remembers the active document as each call ends
  and refuses the next one if it changed while the session has a document
  of its own. Nothing was run.
- **Fix:** call `activate_document` with the document to work on (the
  message names both). Opening, creating, activating, closing and listing
  documents (`_DOCUMENT_CHOOSING_OPERATIONS`) always run.
- **Two clients on one SolidWorks** take turns: each switch makes the other
  one's next call fail this way, which is safe but slow. Give each client its
  own SolidWorks where you can.

### 17. A tool returns `solidworks_busy` or `operation_stopped`

- **`solidworks_busy`:** before each call the server asks SolidWorks' frame
  window, through Win32 only (`IsHungAppWindow`, then `WM_NULL` with
  `SendMessageTimeoutW`), whether it answers. A SolidWorks still busy after
  `SOLIDWORKS_MCP_BUSY_WAIT_SECONDS` (default 30) is not called; nothing ran.
  Usually an earlier call, another program or the user is still running a
  long operation. If it stays busy with no one using it, it is stuck: ask
  the user to end it in Task Manager.
- **`operation_stopped`:** a server loop (`add_fillet`/`add_chamfer` edge
  picking, `select_edges`, `add_outlines`, `check_wall_thickness`) stopped
  between COM calls. Either the call ran past
  `SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS` (default 900; `0` means no
  limit), or the stdio watcher saw the client close its pipe
  (`adapters/solidworks/limits.py`; `SOLIDWORKS_MCP_WATCH_CLIENT=0` turns
  it off). A single COM call can't be interrupted, so the stop lands at the
  next check. New loops that make many COM calls should call
  `limits.check("doing what")` between them.

> **Full COM pitfall catalogue for LLM agents:** `docs/agents/com-api-pitfalls.md`

### Decision order when starting a debug session

1. Read recent `%APPDATA%\Claude\logs\main.log` entries for
   `Launching MCP Server: solidworks` and note the timestamp.
2. Compare to current `SLDWORKS.exe` process start (Task Manager). If SW is
   newer than the server → **#3**: the next call should reconnect; if calls
   keep failing, restart Claude Desktop.
3. If SW is older or same, try a trivial call (`get_model_info`). If it
   returns a circuit-breaker error, wait 60s and retry → **#4**.
4. If real error text surfaces, map to #1/#2/#5/#6 via the error signature
   above.
5. Only then read server source to confirm.

## COM threading architecture

Invariants every new COM-touching code path must respect. Revised 2026-10-21
to match the code (the earlier ComExecutor design is no longer used by the
adapter).

### 1. All COM calls run on the thread that called `connect()`

``_ComSessionCoordinator.connect()`` runs ``pythoncom.CoInitialize()`` and
acquires ``swApp`` on the calling thread, which is the server's asyncio
event-loop thread. Every tool is an ``async`` function that calls the adapter
directly on that loop, and ``_handle_com_operation`` runs its closure
synchronously, so all COM work stays in that one STA apartment.

Consequences:

- Never move adapter calls onto another thread: no ``asyncio.to_thread``,
  ``run_in_executor``, thread pools or synchronous FastMCP tools around
  COM work. ``swApp`` / ``currentModel`` used from another thread raise the
  cross-thread ``AttributeError`` described in runbook item #5, so
  ``_handle_com_operation`` refuses any call from a thread other than the one
  ``initialize_com_apartment`` recorded (``error_type: com_wrong_thread``).
- Do NOT call ``pythoncom.CoInitialize()`` anywhere else in the adapter;
  ``_ComSessionCoordinator`` owns the apartment.
- ``com_executor.ComExecutor`` (a dedicated STA worker thread) is still
  available for standalone scripts such as ``src/utils/convert_step_to_sldprt.py``.

### 2. Every COM operation is followed by a settle pause

``_handle_com_operation`` calls ``_settle_after(operation_name)`` in its
``finally:``: 0.25 s after every operation and 1.0 s after a document
open/create/close (``SOLIDWORKS_MCP_COM_SETTLE_SECONDS`` /
``SOLIDWORKS_MCP_DOC_SETTLE_SECONDS``). Driving SolidWorks 2026 back-to-back
crashed it in its idle-time UI refresh (COM pitfall #26). Route new COM work
through ``_handle_com_operation`` so it gets the pause; unit tests set both
values to 0 in ``tests/conftest.py``.

### 3. Late binding is forced, always

Connection acquires ``swApp`` with ``_dynamic_dispatch`` (a thin wrapper over
``win32com.client.dynamic.Dispatch``) instead of
``win32com.client.Dispatch``. Rationale: when the makepy-generated
``gen_py`` wrapper is loaded (it is, as soon as ``sw_type_info`` is
imported), plain ``Dispatch`` would auto-upgrade to an early-bound wrapper.
Early-bound wrappers reject the VARIANT-based pass-by-ref out-parameters
used by ``OpenDoc6`` and many other SW calls; migrating to ``pythoncom.Missing``
for every such call is a much larger change than we want.

If you add a new COM-touching function: call ``dynamic.Dispatch`` if you
need to acquire a fresh IDispatch, **not** ``EnsureDispatch``.

### 4. Method flagging via sw_type_info

``sw_type_info.flag_methods(obj, *interfaces)`` tells pywin32's late
binding to resolve specific names as methods (``Invoke`` with method
flags) rather than properties. Without flagging, zero-arg SW methods like
``GetTitle()`` raise ``TypeError: 'str' object is not callable`` because
the dispatch returns the string *value*, which Python then tries to call.

Apply flagging:

- On ``swApp`` after acquiring it → ``flag_methods(app, "ISldWorks")``
- On a newly-opened document → ``flag_doc(model, doc_type)`` (infers from
  doc type: Part=1, Assembly=2, Drawing=3)
- On any intermediate dispatch returned from a SW call →
  ``sw_type_info.flagged(x, "IInterfaceName")`` inline-style

Interface names come from the gen_py wrapper (run
``python -m win32com.client.makepy "C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\sldworks.tlb"``
to regenerate after a SW version upgrade).

### 5. Properties are still properties

Not every zero-arg accessor is a method. ``IConfiguration.Name``,
``ModelDoc2.Visible``, etc. are genuine properties — read them without
``()``. If you flag them as methods you'll get the opposite TypeError.
When in doubt, check the gen_py wrapper: methods live in the class body
as regular defs; properties use ``_prop_map_get_`` / ``_prop_map_put_``.

### 6. Regression tests

See ``tests/live/test_live_sw_regression.py`` for the safety net:

- ComExecutor start/stop/exception semantics (the executor scripts use)
- flag_methods incrementality + per-interface correctness
- Late-bound ``swApp`` acquisition
- ``get_model_info`` fields populate correctly
- a call from a worker thread is refused cleanly and the connect thread
  keeps working (``test_com_calls_stay_on_the_connect_thread``)

Run these after any change to ``pywin32_adapter.py``, ``com_executor.py``,
``sw_type_info.py`` or the settle pause::

    $env:SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1
    .\.venv\Scripts\python.exe -m pytest tests/live/test_live_sw_regression.py -v

### Reference sources

- [Problem with OpenDoc6 — SW Forums](https://forum.solidworks.com/thread/19519)
- [OpenDoc6 error — SW Forums](https://forum.solidworks.com/thread/100254)
- [Opendoc6/7 silent open — SW Forums](https://forum.solidworks.com/thread/245676)
- [pywin32 #337 SW pass-by-reference bug](https://sourceforge.net/p/pywin32/bugs/337/)
- [pywin32 #1585 strange issues with SW](https://github.com/mhammond/pywin32/issues/1585)
- [CodeStack SW macros troubleshooting](https://www.codestack.net/solidworks-api/troubleshooting/macros/)
- [SW 2025 SP0 drawing crash thread](https://forum.solidworks.com/forum-solidworks/MYfrK4r0RF6Fnd8tf5tAMA/solidworks-2025-sp0-crashes-when-opening-a-drawing-file)
- [pythoncom CoInitializeEx docs](https://timgolden.me.uk/pywin32-docs/pythoncom__CoInitializeEx_meth.html)
