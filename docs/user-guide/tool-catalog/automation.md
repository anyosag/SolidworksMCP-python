# Automation Tools

Orchestrate multi-step workflows, run batch file processing, manage design tables, generate VBA code on the fly, and tune SolidWorks performance settings. The glue that connects individual tool calls into repeatable pipelines.

> **Prerequisite:** Varies by operation. Batch processing requires writable source/output directories.

**Total tools in this category: 8**

---

### `generate_vba_code`

Write a VBA macro skeleton for an operation you describe: the SolidWorks connection, the active document and optional error handling, with the operation itself left as a TODO.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `operation_description` | `str?` | — | `None` | Description of the operation to generate VBA for |
| `operation_type` | `str?` | — | `None` | Operation type alias |
| `parameters` | `Dict[str, Any]` | ✅ | `` | Operation parameters |
| `target_document` | `str` | — | `Part` | Target document type (Part, Assembly, Drawing) |
| `include_error_handling` | `bool` | — | `True` | Include error handling in generated code |
| `code_style` | `str` | — | `professional` | Code style (simple, professional, advanced) |

**Sample call:**

```json
{
  "parameters": {}
}
```

---

### `automation_start_macro_recording`

Start SolidWorks' macro recorder (the automation family's copy of `start_macro_recording`).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `macro_name` | `str?` | — | `None` | Name for the recorded macro |
| `recording_name` | `str?` | — | `None` | Recording name alias |
| `output_file` | `str?` | — | `None` | Output file alias |
| `recording_mode` | `str?` | — | `None` | Recording mode alias |
| `capture_mouse` | `bool` | — | `True` | Capture mouse actions |
| `capture_keyboard` | `bool` | — | `True` | Capture keyboard actions |
| `description` | `str` | — | `` | Description of the macro functionality |
| `auto_start` | `bool` | — | `True` | Automatically start recording |

**Sample call:**

```json
{}
```

---

### `automation_stop_macro_recording`

Stop a macro recording and save it (the automation family's copy of `stop_macro_recording`).

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `batch_process_files`

Run one operation (rebuild, save as, export or property update) on every matching file in a folder.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_directory` | `str` | ✅ | `` | Directory containing SolidWorks files |
| `operation_type` | `str?` | — | `None` | Type of operation (rebuild, save_as, export, update_properties) |
| `batch_operation` | `str?` | — | `None` | Batch operation alias |
| `target_format` | `str?` | — | `None` | Target format for export operations |
| `file_pattern` | `str?` | — | `None` | File pattern alias |
| `parallel_processing` | `bool` | — | `False` | Parallel processing alias |
| `operation` | `str?` | — | `None` | Operation alias |
| `recursive` | `bool` | — | `False` | Process subdirectories recursively |
| `filter_patterns` | `List[str]` | — | `['*.sldprt', '*.sldasm']` | File patterns to process |

**Sample call:**

```json
{
  "source_directory": "C:\\Temp\\mcp_demo"
}
```

---

### `manage_design_table`

Create, read or update a design table (an Excel sheet that drives a model's configurations).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `table_type` | `str?` | — | `None` | Type of design table (create, update, import) |
| `model_path` | `str?` | — | `None` | Model path alias |
| `table_file` | `str?` | — | `None` | Design table file alias |
| `operation` | `str?` | — | `None` | Operation alias |
| `auto_update` | `bool` | — | `False` | Auto update alias |
| `create_configurations` | `bool` | — | `False` | Create configurations alias |
| `auto_create_configurations` | `bool` | — | `False` | Auto-create alias |
| `excel_file` | `str?` | — | `None` | Excel file path for import/export |
| `parameters` | `List[str]` | — | `[]` | Parameters to include in design table |
| `configurations` | `List[str]` | — | `[]` | Configuration names |

**Sample call:**

```json
{}
```

---

### `execute_workflow`

Run a list of tool steps in order in one call, stopping at the first that fails.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `workflow_name` | `str` | — | `workflow` | A name for the run, used in its messages |
| `steps` | `List[WorkflowStep]` | ✅ | `` | The steps, run one after another: each a {tool, arguments} pair, with an optional document, e.g. {'tool': 'add_line', 'arguments': {'x1': 0, 'y1': 0, 'x2': 10, 'y2': 0}} |
| `rollback_on_error` | `bool` | — | `False` | When a step fails, delete the features and sketches the earlier steps added to the document that was active at the start |
| `detail` | `Literal['summary', 'full']` | — | `summary` | 'summary': each step that worked gives its status, message and small facts (the scalar values of its reply and of each object in it, such as `extrusion.name`, and `measured_change`); 'full': each step's whole reply, as `result`. A failed step always gives its whole reply. |

**Sample call:**

```json
{
  "steps": []
}
```

---

### `create_template`

Create a part, assembly or drawing template file (.prtdot, .asmdot, .drwdot) with standard settings.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `template_type` | `str` | ✅ | `` | Type of template (part, assembly, drawing) |
| `template_name` | `str` | ✅ | `` | Name for the template |
| `base_file` | `str?` | — | `None` | Base file to create template from |
| `source_model` | `str?` | — | `None` | Source model alias |
| `output_path` | `str?` | — | `None` | Output path alias |
| `include_custom_properties` | `bool` | — | `False` | Include custom properties alias |
| `include_materials` | `bool` | — | `False` | Include materials alias |
| `include_features` | `List[str]` | ✅ | `` | Include features alias |
| `metadata` | `Dict[str, Any]` | — | `{}` | Template metadata and properties |

**Sample call:**

```json
{
  "template_type": "example",
  "template_name": "MCP_Demo_Part",
  "include_features": []
}
```

---

### `optimize_performance`

Review SolidWorks' performance settings and apply faster ones.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---
