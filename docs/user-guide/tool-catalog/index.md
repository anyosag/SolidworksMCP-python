# Tool Catalog — All 101 Tools

This reference documents all **165 MCP tools** registered by the SolidWorks MCP server.
Each section covers one functional category with parameter tables and copy-paste sample calls.

## Quick Navigation

| Category | Count | Description |
|----------|-------|-------------|
| [Modeling Tools](modeling.md) | 35 | Create and manipulate SolidWorks parts, assemblies, and drawings. These are the … |
| [Sketching Tools](sketching.md) | 22 | Build 2-D sketch geometry (lines, circles, arcs, splines, polygons) and apply ge… |
| [Drawing Tools](drawing.md) | 14 | Create and edit 2-D technical drawings: add projected/section/detail views, plac… |
| [Drawing Analysis Tools](drawing-analysis.md) | 8 | Quality-gate your drawings. Analyse dimensions, annotations, view coverage, and … |
| [Drawing Automation Tools](drawing-automation.md) | 7 | Put the model's dimensions on a drawing and lay them out so nothing overlaps, ad… |
| [Engineering Data Tools](engineering-data.md) | 8 | Read and edit the data drawings, BOMs and analyses are built from: every model d… |
| [Analysis Tools](analysis.md) | 7 | Extract engineering properties from models: mass, volume, centre of mass, moment… |
| [Export Tools](export.md) | 7 | Convert SolidWorks models to industry-standard interchange and manufacturing for… |
| [File Management Tools](file-management.md) | 19 | Open, save, and manage SolidWorks documents. Load parts and assemblies, save-as … |
| [Automation Tools](automation.md) | 8 | Orchestrate multi-step workflows, run batch file processing, manage design table… |
| [VBA Generation Tools](vba-generation.md) | 10 | Generate and execute VBA macro code for operations that exceed the COM direct-ca… |
| [Template Management Tools](template-management.md) | 6 | Create, extract, apply, compare, and library-manage SolidWorks document template… |
| [Macro Recording Tools](macro-recording.md) | 7 | Record, replay, analyse, and optimize SolidWorks VBA macros. Create macro librar… |
| [Docs Discovery Tools](docs-discovery.md) | 5 | Look up SolidWorks API interfaces, methods and properties, with each member's pa… |

## Standard Response Envelope

A successful call returns at least:

```json
{
  "status": "success",
  "message": "Human-readable description",
  "data": { ... },
  "execution_time": 0.123
}
```

Every tool runs inside one error boundary, so a failed call always has the
same shape, whatever went wrong:

```json
{
  "status": "error",
  "message": "What failed and why",
  "error_type": "no_active_document",
  "hint": "Open or create a document first (open_model / create_part), or activate one with activate_document, then retry.",
  "execution_time": 0.012
}
```

`data` appears on an error only when the adapter returned diagnostics worth
keeping (for example `rebuild_model` lists the failing features). `error_type`
says what kind of failure it was; `hint` is the next step to take:

| `error_type` | Meaning |
|---|---|
| `invalid_input` | The arguments failed validation; nothing was sent to SolidWorks |
| `not_supported` | The active adapter cannot do this (e.g. the mock adapter, or a missing capability) |
| `no_active_document` | The tool needs an open document and there is none |
| `no_active_sketch` | The tool needs an open sketch and there is none |
| `wrong_document_type` | The active document is the wrong kind (e.g. a part where a drawing is needed) |
| `not_found` | A named feature, document, view, file, face or edge does not exist |
| `solidworks_unavailable` | SolidWorks was closed or crashed (RPC disconnect); the next call after it is started reconnects |
| `solidworks_reconnected` | SolidWorks restarted and the server reconnected to it; the call did nothing and earlier documents are gone |
| `active_document_changed` | Someone else switched the active document since the last call; nothing was done until `activate_document` picks one |
| `solidworks_busy` | SolidWorks didn't answer for `SOLIDWORKS_MCP_BUSY_WAIT_SECONDS`; nothing was run, retry once it is free |
| `operation_stopped` | The call stopped part-way: past `SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS`, or the client went away |
| `circuit_open` | Calls are paused after repeated failures; retry after the breaker timeout |
| `com_wrong_thread` | A SolidWorks call ran off the thread that connected (a server bug; restart the server) |
| `com_member_not_found` | SolidWorks could not resolve an API member (usually a stale `gen_py` cache) |
| `com_type_mismatch` | SolidWorks rejected an argument's COM type (a server bug; report it) |
| `operation_failed` | SolidWorks refused or failed the operation; read `message` |
| `internal` | An unexpected server error (a bug; report the tool and arguments) |

## Calling Tools from an LLM

Pass parameters as a JSON object.  Only **required** fields (marked ✅) must be included.
All others default to sensible values.

```text
Goal: calculate mass of the open model

Tool: calculate_mass_properties
Payload: {}
```

```text
Goal: export active part to STEP

Tool: export_step
Payload:
{  "file_path": "C:\\Temp\\part.step" }
```