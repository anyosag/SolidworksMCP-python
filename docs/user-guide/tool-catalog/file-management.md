# File Management Tools

Open, save, and manage SolidWorks documents. Load parts and assemblies, save-as with new names or paths, manage custom file properties, and convert between file formats.

> **Prerequisite:** SolidWorks running. File-write operations need writable output paths.

**Total tools in this category: 19**

---

### `save_file`

Save the active document, to its own path or to a new path in its own format.

**Prerequisite:** Active open document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str?` | — | `None` | Optional output path. If omitted, saves the current active document. |
| `overwrite_modified_references` | `bool` | — | `False` | _OVERWRITE_REFERENCES_DESCRIPTION |

**Sample call:**

```json
{}
```

---

### `save_as`

Save the active document under a new path, as a SolidWorks file or in an exchange format such as STEP or IGES.

**Prerequisite:** Active open document, writable output path

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path for the new file |
| `format_type` | `str` | — | `solidworks` | File format (solidworks, step, iges, etc.) |
| `overwrite` | `bool` | — | `False` | Overwrite existing file |
| `overwrite_modified_references` | `bool` | — | `False` | _OVERWRITE_REFERENCES_DESCRIPTION |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `get_file_properties`

Report the active document's file details: name, path, size, dates, type, configuration and unsaved changes.

**Prerequisite:** Active document

**Sample call:**

```json
{}
```

---

### `get_model_info`

Report the active document's title, path, type, active configuration, unsaved changes, feature count and rebuild status.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `list_features`

List the feature tree of the active part or assembly, in tree order (oldest first).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `include_suppressed` | `bool` | — | `False` | Include suppressed features in the returned list |
| `max_assembly_depth` | `int` | — | `2` | For Assembly documents, how many levels of sub-assembly to recurse into when flattening component features. Ignored for Part documents. |
| `include_standard` | `bool` | — | `True` | false drops what every tree has: the Origin, the three default planes, the Mates folder and the system folders (History, Sensors, Annotations, Solid Bodies, Equations, Material, Lights Cameras and Scene, Favorites, Selection Sets and so on). Folders you made stay. |
| `types` | `List[str]?` | — | `None` | Keep only features of these types (the `type` each entry shows, any case), e.g. ['Extrusion', 'Cut', 'Fillet', 'ProfileFeature']; a sketch is 'ProfileFeature'. An Instant3D extrude whose kind SolidWorks doesn't say ('ICE') matches 'Extrusion' and 'Cut' |
| `last` | `int?` | — | `None` | Keep only the newest N features: the bottom of the tree (the list stays in tree order, oldest first). In an assembly, the newest N of each document. Applied after include_standard and types |

**Sample call:**

```json
{}
```

---

### `get_selected_entities`

Describe the faces, edges and vertices selected in the SolidWorks window right now.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `classify_feature_tree`

Classify the active model's kind (part, sheet metal, assembly, drawing and so on) from its feature tree, and suggest how to work on it.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `include_suppressed` | `bool` | — | `True` | Include suppressed features when reading the active model tree |
| `model_info` | `Dict[str, Any]?` | — | `None` | Optional pre-fetched model info payload to classify without re-reading the active model |
| `features` | `List[Dict[str, Any]]?` | — | `None` | Optional feature-tree payload to classify without re-reading the active model |

**Sample call:**

```json
{}
```

---

### `list_configurations`

List the names of the active model's configurations.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `manage_file_properties`

Read or change the file-level properties of a SolidWorks file on disk.

**Prerequisite:** Active document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `operation` | `str` | ✅ | `` | Operation to perform (copy, move, delete, rename) |
| `source_path` | `str?` | — | `None` | Source file path |
| `file_path` | `str?` | — | `None` | Alternative file path |
| `target_path` | `str?` | — | `None` | Target file path (for copy/move/rename) |
| `properties` | `Dict[str, Any]?` | — | `None` | File properties to set |
| `parameters` | `Dict[str, Any]?` | — | `None` | Operation parameters |
| `include_system` | `bool` | — | `False` | Include system properties |

**Sample call:**

```json
{
  "operation": "example"
}
```

---

### `convert_file_format`

Convert a SolidWorks file on disk to another format without opening it first.

**Prerequisite:** Valid source file path

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_file` | `str` | ✅ | `` | Source file path |
| `target_file` | `str?` | — | `None` | Target file path |
| `source_format` | `str?` | — | `None` | Source file format |
| `target_format` | `str` | ✅ | `` | Target file format |
| `output_path` | `str?` | — | `None` | Alternative output path |
| `conversion_options` | `Dict[str, Any]?` | — | `None` | Conversion options |
| `quality` | `str` | — | `high` | Conversion quality |
| `units` | `str` | — | `mm` | Units |
| `invalid_format` | `str?` | — | `None` | Invalid format for testing |

**Sample call:**

```json
{
  "source_file": "example",
  "target_format": "example"
}
```

---

### `batch_file_operations`

Copy, move, rename or delete SolidWorks files on disk in one call.

**Prerequisite:** Writable directories

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `operation` | `str` | ✅ | `` | Operation to perform (copy, move, delete, rename) |
| `source_path` | `str?` | — | `None` | Source file path |
| `file_path` | `str?` | — | `None` | Alternative file path |
| `target_path` | `str?` | — | `None` | Target file path (for copy/move/rename) |
| `properties` | `Dict[str, Any]?` | — | `None` | File properties to set |
| `parameters` | `Dict[str, Any]?` | — | `None` | Operation parameters |
| `include_system` | `bool` | — | `False` | Include system properties |

**Sample call:**

```json
{
  "operation": "example"
}
```

---

### `load_part`

Open a part (.sldprt) from disk and make it the active document.

**Prerequisite:** SolidWorks running, valid .sldprt path

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path to the .sldprt file |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `load_assembly`

Open an assembly (.sldasm) from disk and make it the active document.

**Prerequisite:** SolidWorks running, valid .sldasm path

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path to the .sldasm file |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `save_part`

Save the active part in place, or as a new .sldprt with the target path checked first.

**Prerequisite:** Active Part document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str?` | — | `None` | Optional output path. If omitted, saves the active part to its existing location. |
| `overwrite` | `bool` | — | `False` | Overwrite existing file |

**Sample call:**

```json
{}
```

---

### `save_assembly`

Save the active assembly in place, or as a new .sldasm, optionally copying the parts it uses alongside.

**Prerequisite:** Active Assembly document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str?` | — | `None` | Optional output path. If omitted, saves the active assembly to its existing location. |
| `overwrite` | `bool` | — | `False` | Overwrite existing file |
| `include_references` | `bool` | — | `False` | When true and file_path is set, copy referenced assembly files into the target folder. |
| `overwrite_modified_references` | `bool` | — | `False` | _OVERWRITE_REFERENCES_DESCRIPTION |

**Sample call:**

```json
{}
```

---

### `pack_and_go_assembly`

Copy an assembly and every part it references into one folder, with the references updated (SolidWorks Pack and Go).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_path` | `str` | ✅ | `` | Absolute path to the source .sldasm file |
| `target_dir` | `str` | ✅ | `` | Directory where the assembly and all referenced parts will be copied |
| `export_preview` | `bool` | — | `True` | Export an isometric PNG preview next to the copied files |
| `overwrite` | `bool` | — | `False` | Overwrite files that already exist in target_dir |

**Sample call:**

```json
{
  "source_path": "C:\\Temp\\mcp_demo\\file.sldprt",
  "target_dir": "example"
}
```

---

### `list_open_documents`

List every document open in SolidWorks and say which one is active.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `activate_document`

Make an already-open document the active one, so the next tools act on it.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `title_or_path` | `str` | ✅ | `` | Window title (e.g. 'bracket.SLDPRT'), full path, or bare file name of a document that is already open |

**Sample call:**

```json
{
  "title_or_path": "C:\\Temp\\mcp_demo\\file.sldprt"
}
```

---

### `save_body_as_part`

Save one solid body of the active multibody part as a new part file (Insert > Features > Save Bodies).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `body_name` | `str` | ✅ | `` | Name of a solid body in the active part, e.g. 'Boss-Extrude1' |
| `file_path` | `str` | ✅ | `` | Absolute path for the new .sldprt (parent directory must exist) |

**Sample call:**

```json
{
  "body_name": "MCP_Demo_Part",
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---
