# Export Tools

Convert SolidWorks models to industry-standard interchange and manufacturing formats: STEP, IGES, STL, PDF, DWG, and raster images. Includes a batch-export tool for processing whole directories.

> **Prerequisite:** An active document or a valid file path to an existing model.

**Total tools in this category: 7**

---

### `export_step`

Export the active document to STEP, like File > Save As with the STEP type.

**Prerequisite:** Active or specified model document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path for the exported file |
| `format_type` | `str?` | — | `None` | Not needed: the file extension sets the format; defaults to the tool's own format |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `export_iges`

Export the active document to IGES, like File > Save As with the IGES type.

**Prerequisite:** Active or specified model document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path for the exported file |
| `format_type` | `str?` | — | `None` | Not needed: the file extension sets the format; defaults to the tool's own format |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `export_stl`

Export the active document to STL, like File > Save As with the STL type.

**Prerequisite:** Active or specified model document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path for the exported file |
| `format_type` | `str?` | — | `None` | Not needed: the file extension sets the format; defaults to the tool's own format |
| `resolution` | `Literal['coarse', 'fine', 'custom']?` | — | `None` | Mesh resolution for this file: coarse, fine, or custom with deviation_mm and angle_deg. Left out: the user's STL setting |
| `deviation_mm` | `float?` | — | `None` | Largest distance between the mesh and the true surface, in mm. Smaller is finer; it makes the resolution custom |
| `angle_deg` | `float?` | — | `None` | Largest angle between neighbouring facets, in degrees. Smaller is finer on small curved details; it makes the resolution custom |
| `units` | `Literal['mm', 'cm', 'm', 'in', 'ft']?` | — | `None` | Units written in the file. Left out: the user's STL setting |
| `binary` | `bool?` | — | `None` | Binary STL (true) or ASCII (false). Left out: the user's setting |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `export_pdf`

Export the active document to PDF, like File > Save As with the PDF type.

**Prerequisite:** Active or specified drawing document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path for the exported file |
| `format_type` | `str?` | — | `None` | Not needed: the file extension sets the format; defaults to the tool's own format |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `export_dwg`

Export the active document to DWG, like File > Save As with the DWG type.

**Prerequisite:** Active or specified drawing document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path for the exported file |
| `format_type` | `str?` | — | `None` | Not needed: the file extension sets the format; defaults to the tool's own format |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `export_image`

Save a picture of the active model, in a standard view or as it is on screen, as PNG or JPG.

**Prerequisite:** Active document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str?` | — | `None` | Full path for the exported image |
| `output_path` | `str?` | — | `None` | Alternative output path |
| `model_path` | `str?` | — | `None` | Path to the model file |
| `format_type` | `str` | — | `jpg` | Image format (jpg, png, bmp, tiff) |
| `format` | `str?` | — | `None` | Alternative format field |
| `image_format` | `str?` | — | `None` | Image format alias |
| `width` | `int` | — | `1920` | Image width in pixels |
| `height` | `int` | — | `1080` | Image height in pixels |
| `resolution` | `str?` | — | `None` | Resolution alias |
| `view_orientation` | `str` | — | `isometric` | View to turn the model to (front, back, left, right, top, bottom, isometric, dimetric, trimetric), or current to keep the view on screen exactly as it is, zoom included |
| `orientation` | `str?` | — | `None` | Alias of view_orientation |
| `zoom_to_fit` | `bool?` | — | `None` | Zoom so the whole model fills the picture. Left out: yes for a named view, no for current, so a close-up stays a close-up |
| `zoom_box_mm` | `List[float]?` | — | `None` | Zoom to this part of the model: two opposite corners of a box in model coordinates, mm, as [x1, y1, z1, x2, y2, z2] |
| `hide` | `List[DisplayType]?` | — | `None` | Hide these for the picture only, e.g. ["planes", "sketches"]; they are shown again afterwards as they were |
| `section` | `ImageSection?` | — | `None` | Cut the model on a plane for this picture only, with the cut faces capped, e.g. {"plane": "Front Plane", "offset_mm": 0}, to show a snap inside its socket; the cut is taken off afterwards |

**Sample call:**

```json
{}
```

---

### `batch_export`

Export every matching SolidWorks file in a folder to one format.

**Prerequisite:** Writable source and output directories

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_directory` | `str` | ✅ | `` | Directory containing SolidWorks files |
| `output_directory` | `str` | ✅ | `` | Directory for exported files |
| `format_type` | `str?` | — | `None` | Target export format |
| `export_format` | `str?` | — | `None` | Alternative export format |
| `file_pattern` | `str?` | — | `None` | File pattern alias |
| `recursive` | `bool` | — | `False` | Search subdirectories recursively |
| `include_subdirectories` | `bool` | — | `False` | Include subdirectories in search |
| `file_patterns` | `List[str]` | — | `['*.sldprt', '*.sldasm', '*.slddrw']` | File patterns to include |

**Sample call:**

```json
{
  "source_directory": "C:\\Temp\\mcp_demo",
  "output_directory": "C:\\Temp\\mcp_demo\\exports"
}
```

---
