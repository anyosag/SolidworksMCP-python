# Macro Recording Tools

Record, replay, analyse, and optimize SolidWorks VBA macros. Create macro libraries for reuse, batch-execute recorded macros, and profile performance hot-spots. Ideal for capturing manual workflows and converting them to automated, repeatable sequences.

> **Prerequisite:** SolidWorks running. Macro execution requires a valid .swp file path.

**Total tools in this category: 7**

---

### `start_macro_recording`

Start SolidWorks' macro recorder, to capture what the user does as a macro.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `macro_name` | `str?` | — | `None` | Name for the recorded macro |
| `recording_name` | `str?` | — | `None` | Alternative recording name |
| `description` | `str` | — | `` | Description of macro functionality |
| `output_file` | `str` | ✅ | `` | Output file for the recorded macro |
| `recording_mode` | `str` | — | `User actions` | Recording mode |
| `capture_mouse` | `bool` | — | `True` | Capture mouse actions |
| `capture_keyboard` | `bool` | — | `True` | Capture keyboard actions |
| `recording_quality` | `str` | — | `High` | Recording quality level |
| `auto_cleanup` | `bool` | — | `False` | Cleanup temporary files |
| `auto_stop` | `bool` | — | `False` | Auto-stop recording after timeout |
| `timeout_seconds` | `int` | — | `300` | Timeout for auto-stop in seconds |

**Sample call:**

```json
{
  "output_file": "example"
}
```

---

### `stop_macro_recording`

Stop the macro recorder and save the recorded macro.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `execute_macro`

Run a binary SolidWorks macro (.swp, or legacy .swb) in the running SolidWorks, calling its `main` procedure once.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `macro_path` | `str?` | — | `None` | Path to a binary SolidWorks macro (.swp, or legacy .swb). VBA source (.vb, .bas, text) cannot be run directly. |
| `macro_file` | `str?` | — | `None` | Alternative to macro_path (.swp or .swb) |
| `proc_name` | `str` | — | `main` | The macro procedure to call; main by default |
| `repeat_count` | `int` | — | `1` | How many times to run the macro (1-100); it stops at the first failure |
| `pause_between_runs` | `float` | — | `0.0` | Seconds to wait between runs |

**Sample call:**

```json
{}
```

---

### `analyze_macro`

Analyse a macro's structure, dependencies and complexity, and suggest optimisations.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `macro_path` | `str?` | — | `None` | Path to macro file to analyze |
| `macro_file` | `str?` | — | `None` | Alternative macro file path |
| `analysis_type` | `str` | — | `full` | Analysis type (full, dependencies, performance) |
| `analysis_depth` | `str` | — | `Basic` | Analysis depth alias |
| `suggest_optimizations` | `bool` | — | `False` | Suggest optimizations |

**Sample call:**

```json
{}
```

---

### `batch_execute_macros`

Run several macros in sequence against the files in a folder.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `macro_list` | `List[str]` | ✅ | `` | List of macro file paths |
| `target_directory` | `str?` | — | `None` | Target directory alias |
| `source_directory` | `str?` | — | `None` | Source directory alias |
| `file_pattern` | `str?` | — | `None` | File pattern alias |
| `execution_order` | `str` | — | `sequential` | Execution order (sequential, parallel) |
| `stop_on_error` | `bool` | — | `True` | Stop batch if error occurs |

**Sample call:**

```json
{
  "macro_list": []
}
```

---

### `optimize_macro`

Suggest improvements to a macro's code for speed and reliability.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `create_macro_library`

Set up a shared folder of categorised, documented macros.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---
