# MCP speed review

A read-and-measure review of where wall-clock time goes when an agent uses
this server, from server start to the last tool result, with a ranked list of
changes. The findings were then implemented on the same branch; see
[What was implemented](#what-was-implemented) for what changed, the switches
that turn each change off, and what still needs a live check.

- **Date:** 2026-11-10, on `main` at v2.0.0 (`f84e60f`).
- **Machine:** Windows 11, SOLIDWORKS 2026 SP4.1 Student installed, Python
  3.13.18 in a `uv` environment.
- **Not driven:** live SolidWorks. Every number below is either **measured**
  (mock mode, or the real server stack with a fake COM object, or files on
  disk) or **estimated** (derived, with the derivation given). Findings that
  need a live number list the measurement to take in
  [Live measurements to take](#live-measurements-to-take).
- **Overlap:** a parallel change (`feat/keep-minimized`) is editing `connect`,
  `_handle_com_operation`, `export_image` and the save-option constants in
  `pywin32_adapter.py`, the save paths and `close_model` in
  `adapters/solidworks/io.py`, and adding `adapters/solidworks/window.py` and
  `dialogs.py`. Findings that touch those areas say so.

## Where the time goes in one task

The skill's own worked example, "a plate with a hole and rounded top edges"
(`skills/solidworks-mcp/references/workflows.md`), is 16 tool calls when the
agent starts with `get_model_info` as the skill asks. Its time budget:

| Part of the task | Time | Basis |
| --- | --- | --- |
| Agent turns (16 tool calls, one model turn each) | 50–100 s | **Estimated** at 3–6 s per turn; measure it (L6) |
| Settle pauses after COM operations | 6.0 s | **Computed** from the code: 20 operations at 0.25 s plus `create_part` at 1.0 s (constants measured at 250 ms per operation) |
| `create_part` loading the default template | ~5 s | Measured by the keep-minimized session |
| Re-flagging fresh document dispatches | 0.5–1 s | **Estimated**: 2–4 rounds of ~906 `GetIDsOfNames` calls at ~0.25 ms each |
| SolidWorks doing the actual modelling | unknown | Needs a live run |
| The server's own Python (FastMCP, error boundary, router, circuit breaker, adapter) | 5 ms | **Measured**: 0.32 ms per tool call |
| Tool replies added to the agent's context | 1.4k tokens | **Measured** on the mock: the plate plus a `list_features`, 17 calls |

Two things follow. The number of agent round trips dominates, so the biggest
win is doing a common job in fewer tool calls (finding 1). Of the server-side
time, the settle pause is the largest piece the server controls, and most of
it is spent while the agent would be thinking anyway (finding 2).

## Ranked findings

Ranked by expected wall-clock saved per agent task, weighed against risk.
**Overlap** means the change touches files the keep-minimized work is
changing; land those after it merges.

| # | Finding | Saves (per task unless noted) | Risk | Effort | Overlap |
| --- | --- | --- | --- | --- | --- |
| 1 | No way to run several steps in one call | ~13 of 16 turns on the plate, est. 40–80 s | Low–medium | M | No |
| 2 | Settle pause is paid after the call, while the agent then thinks anyway | ~5.5 s of the plate's 6.0 s | Medium (crash) | S–M | **Yes** |
| 3 | Fresh dispatches are re-flagged with ~900 COM round trips | est. 0.2 s per `get_model_info`; est. 0.26 s per component per assembly `list_features` | Low (a), medium (b) | S / M | Low |
| 4 | `pydantic_ai` and `sqlmodel` imported on every start | 1.35 s per server start (measured) | Very low | S | No |
| 5 | `connect` imports a 6.3 MB gen_py module to read method names | 1.3 s per connect (measured) | Low | S | No (runs inside `connect`) |
| 6 | `connect` runs before the MCP `initialize` reply | est. 1.5 s off startup; much more if SolidWorks isn't running | Medium (COM thread) | M | **Yes** |
| 7 | Tool list is ~48k tokens; 40 tools only return `not_supported` | 10.5k tokens (measured), plus 4–12k from schema compaction | Low | S–M | No |
| 8 | `get_mass_properties` forces a full rebuild on every read | Scales with model size; not measured | Low–medium | S | No |
| 9 | Feature tools read the geometry summary before and after | 0.5 s settle per feature (measured constants) plus the reads | Low | S | Partly (settle) |
| 10 | Skill guidance costs turns | est. 1–5 turns per task | None | S | No |
| 11 | `list_features` walks the tree twice | est. 0.1–0.2 s per part call | Low | S | No |
| 12 | Docs index lives under the process working directory | 0.37 s rebuild per new folder (measured) | None | S | No |
| 13 | No action: wrapper layers, cache, logging, rate limiting, docs auto-refresh | — | — | — | — |

### 1. No way to run several steps in one call

- **Where:** `src/solidworks_mcp/tools/automation.py:492` (`execute_workflow`,
  registered but planned: it returns `not_supported`); input model at
  `automation.py:216`.
- **Cost:** every step of a build is its own agent turn. The plate is 16
  calls; a simple assembly is 20+. At an **estimated** 3–6 s per turn
  (time to first token plus the tool-call output), the turns are most of the
  task's wall-clock. Replies are small (**measured** 1.4k tokens for the
  whole plate on the mock), so the cost is the round trips, not the payloads.
- **Proposal:** implement `execute_workflow` as a sequential step runner at
  the tool layer. It takes `steps: [{tool, arguments}]`, calls each
  registered tool in-process (the same function FastMCP calls, inside its
  error boundary), stops at the first error by default, and returns a compact
  per-step result (`status`, the step's key fields, and `error_type` / `hint`
  on the failing step). Refuse `parallel_execution: true`: COM work is
  single-threaded. Cap the step count (for example 25) so one call can't
  block the event loop for minutes. With it, the plate is about three calls:
  build, `verify_model`, save. Smaller, targeted alternatives worth
  considering alongside it: let `add_fillet` / `add_chamfer` take the
  `select_face_edges` query directly; let feature tools close an open sketch
  themselves; have `set_material` accept a close match instead of needing
  `list_available_materials` first.
- **Risk:** COM threading is unaffected: the steps run in the handler's
  coroutine on the event-loop thread, the same as separate calls, and each
  step keeps its settle pauses. The agent sees intermediate results only at
  the end, so the step results must carry `measured_change` and a clear
  stop point. A long batch is one long tool call, which a client's tool
  timeout could cut off; the step cap bounds it.
- **Effort:** M. **Overlap:** none.

### 2. The settle pause is paid after the call, while the agent then thinks anyway

- **Where:** `src/solidworks_mcp/adapters/pywin32_adapter.py:149-201`
  (`_DOCUMENT_OPERATIONS`, `_settle_after`) and `:2151-2153` (the `finally:`
  that calls it).
- **Cost:** **measured** at exactly 250 ms per COM operation and 1.0 s per
  document operation, added to every tool reply (a no-op through
  `_handle_com_operation` takes 250.3 ms; with the pause at 0 it takes
  under 0.01 ms). Tools that run several operations pay several times:
  `create_extrusion`, `create_revolve` and `create_cut_extrude` run three
  (0.75 s), `verify_model` up to five (1.25 s), and `generate_drawing_package`
  runs 20+. The plate pays 6.0 s.
- **Why the pause exists:** pitfall #26. SolidWorks 2026 crashed in its
  idle-time CommandManager refresh when the next API call arrived while that
  refresh was still running. What protects against it is the *gap* between
  one operation ending and the next starting.
- **Proposal: keep the gap, stop paying for it twice.**
  1. *Pace before, not after.* Record when the last operation ended and what
     kind it was. Before the next COM operation, sleep only what is left of
     the gap: `max(0, gap - (now - last_end))`. When an agent drives the
     server, its turn (seconds) already covers the 0.25–1.0 s gap, so the
     wait drops to zero. Inside one tool or a batch, the gap is enforced
     exactly as now.
  2. *Reads don't open a gap.* An operation that only reads (the list below)
     triggers no UI refresh, so it needn't start a new gap. It still waits
     out the gap of an earlier mutation. Inside a feature tool that removes
     the pause after the before-read, and `verify_model`'s reads stop
     pausing each other.
     Candidates, chosen conservatively: `get_model_info`,
     `list_open_documents`, `list_configurations`, `list_features`,
     `get_dimension`, `get_material`, `list_available_materials`,
     `get_custom_properties`, `list_model_dimensions`, `list_components`,
     `list_drawing_views`, `get_model_geometry_summary`,
     `get_application_info`, `check_sketch_fully_defined`. Keep
     `get_mass_properties` (it rebuilds), `measure_entities` and
     `get_selected_entities` (they select), and `check_interference` as
     mutations.
  3. *Pace at the adapter's entry, not only inside `_handle_com_operation`.*
     Some COM work runs before the closure: `_sync_current_model_from_active`
     reads `ActiveDoc` and flags it, and `list_features` reads `ActiveDoc`.
     Today those calls are covered by the previous call's after-pause. Put
     the pace-before wait where every adapter method enters (for example
     `CircuitBreakerAdapter._execute_with_circuit_breaker`, with the existing
     spot as a fallback when the breaker is off) so they stay covered.
- **Rejected alternative: wait for SolidWorks to go idle.** There is no
  reliable external idle signal. `ISldWorks.CommandInProgress` was tried
  and crashed sooner (pitfall #26). Win32 `WaitForInputIdle` returns at once
  after a process's first idle. A `WM_NULL` round trip through
  `SendMessageTimeout` shows the message loop is pumping, not that the
  MFC `OnIdle` work has finished. Each of these adds code and risk for a
  signal no better than elapsed time.
- **Also considered:** a shorter gap once SolidWorks has been running a
  while (the crashes clustered 2–5 minutes after launch, and the live suite
  waits 480 s). That needs its own soak test (L3). With pacing in place, the
  gap rarely costs anything in agent use, so it matters only for batches.
- **Side effect:** `time.sleep` in the pause blocks the event loop, so MCP
  pings and cancellations wait too (several seconds inside a drawing
  package). Pacing before makes that rarer. Don't switch to `asyncio.sleep`:
  that would let another request's COM work into the gap.
- **Risk:** medium. The gap for mutations is unchanged; the new risk is a
  mutation wrongly listed as a read. Needs the soak test (L3) on a cold
  session and a warmed one before shipping.
- **Effort:** S–M. **Overlap: yes**, `_handle_com_operation`. Land it after
  keep-minimized.

### 3. Fresh dispatches are re-flagged with ~900 COM round trips

- **Where:** `src/solidworks_mcp/adapters/sw_type_info.py:215-259`
  (`flag_methods`, one `_FlagAsMethod` per name, and pywin32's
  `_FlagAsMethod` calls `GetIDsOfNames` once per name);
  `adapters/solidworks/io.py:1330-1361` (`_sync_current_model_from_active`,
  called by `get_model_info` at `io.py:2042`, `set_units` at `:1850`,
  `save_body_as_part` at `:3662`, and `rename_feature`);
  `adapters/solidworks/selection.py:45` and `:235` (`list_features` and
  `get_selected_entities` replace `currentModel` with an unflagged
  `ActiveDoc`); `pywin32_adapter.py:1666-1697` (per assembly component).
- **Cost:**
  - **Measured** from the gen_py wrapper: flagging a part document resolves
    906 distinct names (IModelDoc2 758, IPartDoc 167), an assembly 950, a
    drawing 1,024; `ISldWorks` 330, `IView` 436, `IComponent2` 147,
    `IFeature` 115.
  - **Measured** with a fake dispatch through the real stack:
    `get_model_info` makes **906 `_FlagAsMethod` calls on every call**,
    because `swApp.ActiveDoc` returns a new wrapper each time and the flag
    cache is per object.
  - **Estimated** per round trip at ~0.25 ms, from this repo's own number
    ("~100 names, ~27 ms per object" for `IFeature`, at
    `pywin32_adapter.py:1062-1068`). That makes each `get_model_info` about
    0.23 s, each component in an assembly `list_features` about 0.26 s (a
    10-component assembly is about 2.6 s per call), and each drawing view
    about 0.11 s. L1 checks the per-round-trip figure.
- **Proposal:**
  - **(a) Keep the flagged dispatch when the document hasn't changed.** In
    `_sync_current_model_from_active`, `list_features` and
    `get_selected_entities`, compare the new `ActiveDoc` with
    `currentModel` by COM identity (`active._oleobj_ == current._oleobj_`;
    pywin32 compares the `IUnknown` pointers, which the proxy answers
    locally) and keep `currentModel` when they match. That removes the
    repeat cost for the common case. It also fixes `list_features` leaving an
    *unflagged* dispatch in `currentModel` for the next tool.
  - **(b) Remember DISPIDs per interface.** The first time an interface is
    flagged, keep the `MapEntry` objects `_FlagAsMethod` built; for every
    later object of that interface, copy them into
    `obj._olerepr_.mapFuncs` with no round trips. That is exactly what
    `_FlagAsMethod` does, minus the lookup. The DISPIDs can even come
    offline: the gen_py wrapper holds them (`GetTitle` is 65607,
    `ForceRebuild3` 66227, read with `dis` and no COM), and so does the type
    library (`FUNCDESC.memid`, as `tools/type_library.py` reads). That makes
    the first object free too.
- **Risk:** (a) low. (b) medium: it relies on pywin32 internals
  (`_olerepr_.mapFuncs`, `build.MapEntry`), and on runtime DISPIDs matching
  across objects (memo) or matching the type library (offline). Check both
  with L2 before turning (b) on, and key the memo by interface tuple, so
  part, assembly and drawing documents never share entries.
- **Effort:** (a) S, (b) M. **Overlap:** low. `_sync_current_model_from_active`
  is in `io.py`, the same file as the save paths and `close_model` the other
  session is editing, but it is a different function. `sw_type_info.py` is
  untouched by it.

### 4. `pydantic_ai` and `sqlmodel` are imported on every start

- **Where:** `src/solidworks_mcp/server.py:24`
  (`from pydantic_ai import Agent`, used only by `_setup_agent` when
  `OPENAI_API_KEY` is set and not in mock mode) and `server.py:30`
  (`from .agents.history_db import insert_tool_event`, used only when
  `SOLIDWORKS_MCP_DB_LOGGING` is on; it pulls in the whole `agents` package,
  `sqlmodel` and `sqlalchemy`).
- **Cost (measured):** importing `solidworks_mcp.server` takes 4.35 s; with
  those two imports stubbed out, 3.0 s, so **1.35 s** (31%) of import time is
  spent on code the default path never runs. Mock-mode startup measured from
  spawn to the `initialize` reply: **4.8 s** median of 5. Breakdown: imports
  4.1 s, tool registration 0.27 s, `tools/list` 0.03 s in-process (0.19 s
  over stdio).
- **Proposal:** import both inside the functions that use them.
- **Risk:** very low; no COM involved. Tests that patch
  `solidworks_mcp.server.Agent` or `insert_tool_event` need the new location.
- **Effort:** S. **Overlap:** none.
- **What's left:** about 2.1–2.5 s is FastMCP itself (`import fastmcp` 1.1 s,
  plus 1.0 s more the first time `FastMCP()` is built, as it loads its
  server, sampling and HTTP modules). That is upstream and not worth
  fighting here.

### 5. `connect` imports a 6.3 MB gen_py module to read method names

- **Where:** `src/solidworks_mcp/adapters/sw_type_info.py:65-124`
  (`_load_wrapper`, first run by `flag_methods(app, "ISldWorks")` inside
  `connect`).
- **Cost (measured):** importing the SW 2026 gen_py module takes **1.31 s**
  per process. Scanning it for the 418 interfaces' method names takes 3 ms.
  The same table saved as JSON (194 KB) loads in 10 ms. Nothing else uses
  the wrapper module: only the name sets (`progress/snapshot.py` reads them
  too).
- **Proposal:** cache the name table (and, for finding 3(b), the DISPIDs)
  as JSON in the server's data folder, keyed by the gen_py module name plus
  the file's size and mtime. Import the wrapper only on a cache miss.
- **Risk:** low; a changed type library changes the key. The forced late
  binding in CLAUDE.md is unaffected, since `dynamic.Dispatch` never needs
  the wrapper.
- **Effort:** S. **Overlap:** none in files; it runs inside `connect`.

### 6. `connect` runs before the MCP `initialize` reply

- **Where:** `src/solidworks_mcp/server.py:403-429`: `start()` awaits
  `setup()`, then `adapter.connect()`, and only then starts stdio.
- **Cost (estimated):** with SolidWorks running, the `initialize` reply waits
  for imports (4.35 s, measured), registration (0.27 s, measured) and
  `connect` (gen_py 1.3 s, measured, plus `GetActiveObject`, 330 flags at
  ~0.25 ms, the ready probe, `Visible` and six preference toggles), so about
  6–6.5 s. When SolidWorks isn't running, `Dispatch("SldWorks.Application")`
  launches it inside startup, which can take long enough to hit the client's
  startup timeout. In Claude Code the server shows as "still connecting"
  until then.
- **Proposal:** start stdio first and connect lazily on the first tool call
  that needs the adapter (docs lookups and VBA generators never do), or as a
  task started after the transport is up. Either way it must run on the
  event-loop thread, as now.
- **Risk:** medium. It must stay on the event-loop thread (CLAUDE.md COM
  threading rule 1): no `to_thread` or executor. The first tool call pays
  the connect time instead, and a connect failure reaches the agent as that
  call's error with a hint, which is arguably better. With finding 5 the
  connect is about 0.2 s anyway.
- **Effort:** M. **Overlap: yes**, `connect`.

### 7. The tool list is ~48k tokens, and 40 tools only return `not_supported`

- **Where:** `src/solidworks_mcp/tools/support_levels.py:81` (40 `planned`,
  10 `experimental`, 106 `stable`); the schemas FastMCP builds from the input
  models.
- **Cost (measured,** o200k tokenizer as a proxy; Claude's own count will
  differ): 156 tools are **48.4k tokens** in the form an API client sends
  (name, description, input schema): 17.4k descriptions, 28.4k input
  schemas. The 40 planned tools are **10.5k (22%)**. The heaviest are
  `generate_drawing_package` 1.0k, `add_gtol` 0.85k,
  `generate_vba_extrusion` 0.8k and `verify_model` 0.8k. Schema patterns:
  240 optional fields are written as `anyOf: [{type: X}, {type: null}]` with
  `default: null`; about 50 fields are input aliases (`start_x` beside `x1`);
  every tool wraps its fields in one `input_data` object.
- **What it costs in time:** a client that loads every schema carries these
  tokens on every turn. That costs little while the prompt cache is warm,
  but every cache miss pays to prefill them, and they use up context, so
  long sessions compact sooner. Claude Code in this session deferred the
  SolidWorks tools (names only until `ToolSearch` loads a schema), which
  trades the tokens for extra `ToolSearch` turns. Planned tools also invite
  wasted calls.
- **Proposal, by risk:**
  1. Don't register `planned` tools by default; an environment flag can
     show them for development. Saves 10.5k tokens (measured).
  2. Emit optional fields as their plain type (validation unchanged): about
     −4.0k. Leave alias fields out of the schema while still accepting them
     through validation aliases: about −0.8k more. Both measured on the
     captured schemas.
  3. Flattening `input_data` would save about −7k more, but it changes every
     tool's contract and every test. Not recommended now.
- **Risk:** low; no COM. **Effort:** S–M. **Overlap:** none.

### 8. `get_mass_properties` forces a full rebuild on every read

- **Where:** `src/solidworks_mcp/adapters/solidworks/io.py:2330-2332`
  (`ForceRebuild3(False)`, which rebuilds every feature, sub-assemblies
  included, before reading).
- **Cost:** proportional to the model, and paid by `get_mass_properties`,
  `calculate_mass_properties` and `verify_model` with `mass_kg`. Not
  measured; L4.
- **Proposal:** `EditRebuild3()` (rebuilds only what's out of date), or skip
  the rebuild when `GetRebuildStatus` / `GetUpdateStamp` says nothing
  changed.
- **Risk:** low–medium: verify the mass properties are equal after a
  `set_dimension` (L4). It clears the selection the same as today
  (pitfall #23).
- **Effort:** S. **Overlap:** none.

### 9. Feature tools read the geometry summary before and after

- **Where:** `src/solidworks_mcp/tools/modeling.py:1355-1359`
  (`create_extrusion`), `:1419-1423` (`create_revolve`), `:1577-1580`
  (`create_cut_extrude`).
- **Cost:** two extra COM operations per feature: 0.5 s of settle
  (measured constants) plus body volume and extreme-point reads (not
  measured).
- **Proposal:** finding 2's read rule removes the settle. Beyond that,
  reuse the last "after" summary as the next "before" when
  `IModelDoc2.GetUpdateStamp` (one call) hasn't changed, so the user editing
  the model in the window between calls is still caught.
- **Risk:** low with the stamp check. **Effort:** S. **Overlap:** partly
  (the settle).

### 10. Skill guidance costs turns

- **Where:** `src/solidworks_mcp/skills/solidworks-mcp/SKILL.md` and
  `references/workflows.md`.
- **Proposal (documentation only):**
  - For clients that defer tools (Claude Code), list the core tools of a part
    build so the agent loads all their schemas in one `ToolSearch` call
    instead of one per tool.
  - Pass `material` to `create_part` and skip `list_available_materials`
    when the exact name is known.
  - In "Changing an existing model", call `rebuild_model` only when
    `set_dimension` reports a problem; `set_dimension` already rebuilds.
  - Close documents that are finished (`close_model`) in long sessions. The
    keep-minimized session found that long SolidWorks sessions slow every
    call, and the number of open documents is a likely factor (L7).
- **Risk:** none. **Effort:** S. **Overlap:** none.

### 11. `list_features` walks the tree twice

- **Where:** `src/solidworks_mcp/adapters/pywin32_adapter.py:1544-1608`: a
  forward `GetNextFeature` walk (flagging four members on each feature), then
  a full `FeatureByPositionReverse` walk deduplicated against it.
- **Cost (estimated):** about 15 round trips per feature, or 0.1–0.2 s for a
  part with 20–40 tree entries (the default tree alone has 15 or more). For an
  assembly it adds to finding 3's per-component cost.
- **Proposal:** run the reverse walk only when the forward walk found fewer
  entries than `GetFeatureCount`; finding 3(b) removes the per-feature flags.
- **Risk:** low; the code notes some type-library combinations stop the
  forward walk early, which the count check still catches. **Effort:** S.
  **Overlap:** none.

### 12. The docs index lives under the process working directory

- **Where:** `src/solidworks_mcp/tools/docs_discovery.py:49-53` and `:180`
  (`.generated/docs-index`, relative).
- **Cost (measured):** the first lookup in a folder with no index builds it
  from the type library: 0.37 s, read in-process, without starting
  SolidWorks. Later lookups take 25–60 ms, reading the 2.8 MB index each
  time. The Claude Code entry for this server sets no `cwd`, so the index is
  rebuilt, and a `.generated` folder created, in whatever folder a session
  starts in.
- **Proposal:** keep the index in the server's data folder; hold the parsed
  index in memory between lookups. `SOLIDWORKS_MCP_DOCS_INDEX_AUTO_REFRESH` is
  fine as is: it runs on a lookup, not at startup, and only when the index
  is older than 21 days.
- **Risk:** none. **Effort:** S. **Overlap:** none.

### 13. Checked, no action needed

- **Wrapper layers.** The whole stack (FastMCP `call_tool`, `tool_boundary`,
  `IntelligentRouter`, `CircuitBreakerAdapter`, adapter) costs **0.32 ms**
  per tool call and the adapter path alone 0.09 ms (both measured). The
  router still runs a complexity analysis per call although no operation has
  a VBA route any more (`vba_operation=None`, `server.py:297`). That is
  microseconds, but it is dead work and could go.
- **Response cache.** Caches only analysis and docs results, never live
  model state; nothing to gain.
- **Connection pool.** Off by default (`connection_pooling: False`). If
  turned on, `factory.py:320` hands the pool the *same* adapter for every
  slot, so `connection_pool.py:251-277` would run `connect()` five times at
  startup, and a failed call would disconnect and reconnect the shared
  adapter, with 1–3 s backoffs. Keep it off for COM; consider removing it.
- **Logging.** No logging on the success path of a tool call.
- **Rate limiting.** On by default, but `check_rate_limit` is never called
  from a tool, so it costs nothing (and limits nothing).
- **Docs index auto-refresh.** See finding 12.

## Not reviewed in depth

- **`create_part` template time (~5 s).** `io.py:1554-1567` tries `NewPart`,
  then `NewDocument` with the user-preference template. Before changing
  anything, find out whether the 5 s is paid on every call or only the first
  (L5). If only the first, warming it at connect is tempting, but a document
  operation in SolidWorks' first minutes is exactly pitfall #26's crash
  window.
- **`export_image`, saves and `close_model`.** They belong to the
  keep-minimized change and were left alone. One note for it:
  `_zoom_to_fit` (`pywin32_adapter.py:2266-2302`) redraws twice around the
  zoom, and redraws of a minimized window may be wasted work.

## What was implemented

Every change below has unit tests on the mock or fake-COM path. None has run
against live SolidWorks yet (the keep-minimized session was using it), so each
change that touches COM has a switch to turn it off without a code change.

| # | Change | Where | Switch (default) |
| --- | --- | --- | --- |
| 1 | `execute_workflow` runs up to 25 `{tool, arguments}` steps in order through FastMCP's own `call_tool`, stops at the first failed step (or `continue`), and refuses unknown tools before running anything. Support level: experimental. | `tools/automation.py` | — |
| 2 | Settle gap: wait *before* an operation for what is left of the last one's gap; read-only operations open no gap; the circuit breaker paces each adapter method before its first COM call. | `adapters/pywin32_adapter.py` (`_ComPacer`, `_READ_ONLY_OPERATIONS`), `adapters/circuit_breaker.py` | `SOLIDWORKS_MCP_SETTLE_MODE=gap`; `after` restores the old sleep |
| 3a | Keep the flagged `currentModel` when `ActiveDoc` wraps the same COM object (`sw_type_info.same_com_object`), in `_sync_current_model_from_active`, `list_features` and `get_selected_entities`. | `adapters/solidworks/io.py`, `adapters/solidworks/selection.py` | — |
| 3b | DISPID memo: the DISPIDs the first object of an `(interface, document type)` returns are copied into later objects' method maps, after two canary `GetIDsOfNames` checks; a mismatch disables the memo for that pair. | `adapters/sw_type_info.py` | `SOLIDWORKS_MCP_DISPID_MEMO=1` |
| 4 | `pydantic_ai` and `agents.history_db` imported where used. | `server.py` | — |
| 5 | The method-name table is cached as JSON, keyed by the gen_py file's size and mtime. | `adapters/sw_type_info.py` | `SOLIDWORKS_MCP_TYPEINFO_CACHE=1`, `SOLIDWORKS_MCP_TYPEINFO_CACHE_DIR` |
| 6 | No connect before stdio. A middleware attaches in the background after `notifications/initialized` (only to a running SolidWorks, never launching it), and every tool call connects first if needed. A failed connect isn't retried for 30 s. | `server.py` (`_ConnectOnDemand`, `ensure_connected`), `PyWin32Adapter.is_application_running` | — |
| 7 | Planned tools hidden from the tool list; listed schemas compacted (nullable wrappers and input aliases left out; calls still accept both). | `server.py`, `tools/schema_compaction.py` | `SOLIDWORKS_MCP_SHOW_PLANNED_TOOLS=false`, `SOLIDWORKS_MCP_COMPACT_TOOL_SCHEMAS=true` |
| 8 | `get_mass_properties` calls `EditRebuild3()` instead of `ForceRebuild3(False)`. | `adapters/solidworks/io.py` | — |
| 9 | No separate change: finding 2's read rule removes the before/after reads' settle. Reusing the "after" summary by `GetUpdateStamp` was dropped, because every feature follows a sketch, which changes the stamp, so it would almost never hit. | — | — |
| 10 | Skill: batching with `execute_workflow`, one tool search for all schemas, `create_part` with `material`, closing finished documents, planned tools now hidden. | `skills/solidworks-mcp/` | — |
| 11 | `list_features` runs the reverse walk only when the forward walk visited fewer features than `GetFeatureCount`. | `adapters/pywin32_adapter.py` | — |
| 12 | The docs index lives in the server's cache folder (`<data_dir>/cache/docs-index`), and the last index read is kept in memory while its file is unchanged. | `tools/docs_discovery.py` | — |
| 13 | The router skips its complexity analysis when there is no VBA route. The connection pool was left as it is (off by default). | `adapters/intelligent_router.py` | — |

Supporting changes: `ToolOperationError` takes an optional `classification`,
so `execute_workflow` reports its failed step's own `error_type` and `hint`;
the tests point the type-info cache and the docs index away from the user's
folders.

### Measured after the changes

Same machine and methods as below; all **measured** without SolidWorks.

| What | Before | After |
| --- | --- | --- |
| Mock startup, spawn to `initialize` reply (median of 5) | 4.83 s | 3.42 s |
| `tools/list` reply after `initialize` | 0.19 s | 0.13 s |
| `import solidworks_mcp.server` (+ first `FastMCP()`) | 4.35 s | 2.98 s |
| Method-table load at connect | 1.31 s (gen_py import) | 0.002–0.013 s (cached; the first run still pays 1.26 s and writes the cache) |
| `_FlagAsMethod` calls per `get_model_info` on an unchanged document | 906 | 0 |
| Server Python per tool call (fake COM, pause 0) | 0.32 ms | 0.23 ms |
| Settle waits for the plate's 21 operations, back-to-back | 6.00 s | 3.75 s |
| The same, as 16 tool calls with a 1.0 s agent turn between them | 6.00 s | 0.51 s |
| Tool list (o200k tokens) | 156 tools, 48.4k | 117 tools, 34.3k |

The 0.51 s left is the pause each feature tool's after-read takes behind its
own feature (two features at 0.25 s): the same gap as before, just no
longer added after the reply. Real connects and SolidWorks's own work are
still unmeasured.

### Checked on live SolidWorks (2026-11-10)

SOLIDWORKS 2026 SP4.1, about two hours after launch, with no other session
using it, scratch documents only. **Measured.**

**The plate over stdio.** A client script spawned the server, sent
`initialize` and `notifications/initialized`, waited 2 s for an agent's first
turn, then drove the plate build with a 1.5 s agent turn between calls. The
`main` run used `main` (v2.0.0) on the same virtualenv. All three runs built
the same geometry (volume +60,000 mm³, then −785.4 mm³). `add_fillet` failed
the same way in all three (`FeatureFillet3` added no feature after
`select_face_edges` with `side: top`, `edge_type: linear`), an existing
fault, not a regression.

| | `main` | Branch, one call per step | Branch, `execute_workflow` |
| --- | --- | --- | --- |
| Spawn to `initialize` reply | 4.68 s (includes the connect) | 3.13 s (connects later, in the background) | 3.11 s |
| Tool calls for the build | 13 | 13 | 5 |
| Server time for those calls | 39.1 s | 21.6 s | 21.1 s |
| Wall time including the 1.5 s turns | 58.6 s | 41.1 s | 28.6 s |
| `get_model_info` reply | 6.36 s | 0.16 s | 0.18 s |
| `create_part` reply | 8.18 s | 7.30 s | 7.05 s |

The background attach connected before the first tool call, with the method
table read from the cache. With real agent turns (3–6 s rather than 1.5 s),
the 8 calls `execute_workflow` saves are worth a further 24–48 s.

**Per-change checks.**

| Check | Result |
| --- | --- |
| L1: flagging a fresh part wrapper, memo off | 0.31–0.66 s (896 names; 0.34–0.73 ms each, two to three times the earlier 0.25 ms estimate) |
| L1: the same with the memo | 0.004 s |
| Memo-filled DISPIDs against SolidWorks' own `GetIDsOfNames` | 896 of 896 match on a part, 943 of 943 on an assembly |
| L2: two parts | identical DISPIDs |
| L2: part against assembly, `IModelDoc2` names | **19 differ**: exactly the names `IModelDoc2` shares with `IPartDoc` (`FirstFeature`, `EditSuppress`, `Dummy1`–`8`, …). See below. |
| 3a: `ActiveDoc` against the flagged `currentModel` | recognised as the same object; `get_model_info` kept the flagged model |
| L4: mass after `set_dimension` 10 → 20 mm | 60,000 → 120,000 mm³ with `EditRebuild3`, the same after `ForceRebuild3` (0.17 s each on this small part) |
| Pacing soak (L3), `tests/live/test_live_sw_regression.py` in gap mode at the production pauses (0.25 s / 1.0 s) | No crash. First pass: 45 passed before `-x` stopped at the failure below (3.5 min). Second full pass with it deselected: 56 passed, 2 skipped (no local test assembly), 5.6 min. No memo-mismatch warnings. |
| `test_list_features_assembly_resolves_real_components_and_subassembly` | Fails ("sub-assembly recursion did not surface nested parts"), identically on `main` v2.0.0 and with the memo off: an existing failure. |

**A memo fault the live check found, and its fix.** A document's dispatch
resolves a name that both `IModelDoc2` and the document's own interface
declare to the document type's DISPID. The first version keyed plain
`flag_methods(doc, "IModelDoc2")` calls with no document type, so a part's
numbers could have reached an assembly through those 19 names and invoked the
wrong method; its two canaries would not have noticed. Now document
interfaces use the memo only with a known document type, the canaries always
include names shared by document interfaces, and
`_sync_current_model_from_active` no longer guesses "part" for a document
whose type it can't read.

**A hazard for live testing, not specific to this branch.** An earlier
attempt at the `main` run collided with another session working in
SolidWorks: after `create_part` that session's part was active,
`get_model_info` followed it, and four plate features landed in it (since
removed). Any tool that re-reads `ActiveDoc` follows a document switch made by
someone else, in `main` as on this branch. Live checks need SolidWorks to
themselves.

### Still to check

- **Pacing on a cold SolidWorks:** the soak ran on a session about two hours
  old; pitfall #26's crashes came in the first minutes after launch.
- **Connect on demand with SolidWorks closed:** the first tool call should
  launch it. Not run: SolidWorks was in use.
- **`execute_workflow` to stable:** a live demo the user signs off, once the
  `add_fillet` fault above is understood.

## Live measurements to take

Written before any live run. L1, L2, L4 and a warmed L3 have since been run
(see [Checked on live SolidWorks](#checked-on-live-solidworks-2026-11-10));
L3 on a cold session and L5–L8 are still open. Each one is read-only or uses
a scratch part.

| ID | Measure | How | Decides |
| --- | --- | --- | --- |
| L1 | Cost of one `GetIDsOfNames` round trip | Time `sw_type_info.flag_doc(swApp.ActiveDoc, 1)` on a fresh dispatch, 10 times | Finding 3's savings (expect ~0.2 s per part document) |
| L2 | DISPID stability | For two part documents (then an assembly and a drawing), compare `_oleobj_.GetIDsOfNames(0, name)` for every flagged name with each other and with the gen_py / type-library DISPIDs | Whether 3(b) can use a memo, or offline DISPIDs |
| L3 | Pacing soak test | Run `tests/live/test_live_sw_regression.py` with pace-before and the read rule, once on a cold SolidWorks (under 8 minutes old) and once warmed | Whether finding 2 is safe |
| L4 | Full versus incremental rebuild | On a 30-feature part, time `ForceRebuild3(False)` against `EditRebuild3()` before `CreateMassProperty`, after a `set_dimension`, and compare the volumes | Finding 8 |
| L5 | Template load | Time `create_part` twice in a row in a fresh session; `NewPart` against `NewDocument(template)`; minimized against normal | Whether anything can be done about the 5 s |
| L6 | Agent turn time | From a Claude Code transcript of a real build, the time between each tool result and the next tool call | The weight of finding 1 against the rest |
| L7 | Long-session slowdown | `get_model_info` latency with 1, 10 and 30 documents open | Whether closing documents (finding 10) is the fix |
| L8 | Real startup | Server log timestamps from launch to `initialize` with SolidWorks running, and with it closed | Findings 5 and 6 |

## How the numbers were taken

All on the machine above, in a `uv` environment built from `uv.lock`, with
SolidWorks not driven. Scripts were throwaway; each is described well enough
to repeat.

- **Startup over stdio:** spawn `solidworks-mcp.exe --mock`, send
  `initialize`, `notifications/initialized` and `tools/list` as raw JSON-RPC
  lines, and time each reply from the spawn. 5 runs; medians: `initialize`
  4.83 s, `tools/list` reply 0.19 s after it.
- **Startup phases:** in one fresh process, time `import fastmcp`, the rest
  of `import solidworks_mcp.server`, `load_config`, `SolidWorksMCPServer()`,
  `validate_environment`, `setup_security`, `create_adapter`,
  `register_tools` and `list_tools`. 3 runs; total 4.37–4.45 s.
- **Import counterfactual:** the server import with `pydantic_ai` and
  `solidworks_mcp.agents` stubbed in `sys.modules` (3.0 s, and
  `sqlalchemy` never loaded) against the real import (4.35 s); 3 runs each.
- **gen_py:** `gencache.GetModuleForTypelib(SW_TLB_IID, 0, 34, 0)` timed
  alone, the class scan timed alone, and the resulting table round-tripped
  through JSON. 2 runs.
- **Per-call overhead:** the real non-mock server stack (`setup()` with
  `adapter_type: pywin32`), with a pure-Python stand-in for
  `SldWorks.Application` whose `ActiveDoc` returns a new object on each read
  and whose `_FlagAsMethod` counts calls. 300 calls of
  `mcp.call_tool("get_model_info")` with the settle pause at 0, then 5 at
  the default.
- **Tool list tokens:** the captured `tools/list` reply, each tool reduced
  to `{name, description, input_schema}` and counted with `tiktoken`'s
  `o200k_base`; the schema rewrites in finding 7 applied to the same JSON
  and counted again.
- **Workflow replies:** the plate workflow run on the mock adapter through
  `mcp.call_tool`, counting each reply's tokens.
- **Docs lookups:** `lookup_api_method` four times in a clean folder (first
  one builds the index from the type library in-process).
- **Mock test suite**, for a baseline: 3,737 passed, 15 skipped in 284 s.
