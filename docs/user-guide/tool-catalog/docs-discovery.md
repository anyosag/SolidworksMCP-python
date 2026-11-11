# Docs Discovery Tools

Look up SolidWorks API interfaces, methods and properties, with each member's parameters, return type and description, read from the installed SolidWorks type library. The lookup tools build the JSON index themselves the first time they run, and reuse it after that.

> **Prerequisite:** SolidWorks installed (it need not be running), Windows with pywin32. The server's --year picks which installed release answers.

**Total tools in this category: 5**

---

### `discover_solidworks_docs`

Rebuild the SolidWorks API index on purpose. The lookups don't need it.

**Prerequisite:** SolidWorks installed (it need not be running), Windows only

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `output_dir` | `str?` | — | `None` | Folder to save the index in; default .generated/docs-index. The lookups only read the default folder, so another folder is for keeping a copy (pass it back as index_file). |
| `include_vba` | `bool` | — | `True` | Also list the VBA type libraries registered on this machine |
| `year` | `int?` | — | `None` | SolidWorks year whose type library to read, e.g. 2026; an error if that year isn't installed. Unset: the year the server was started with (--year), else the newest installed. |

**Sample call:**

```json
{}
```

---

### `search_solidworks_api_help`

Search SolidWorks API interface and member names by keyword.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year` | `int?` | — | `None` | SolidWorks year whose API to answer for, e.g. 2026. Usually leave unset: the server's --year, else the newest installed. A year that isn't installed is explained in the result's note. |
| `index_file` | `str?` | — | `None` | Path to a saved index JSON to answer from instead of the installed type library, e.g. one copied from another machine. Rarely needed. |
| `query` | `str` | ✅ | `` | Words to find in interface and member names, e.g. 'chamfer' or 'SelectByID2' |
| `max_results` | `int` | — | `10` | Maximum number of matches to return |
| `auto_discover_if_missing` | `bool` | — | `False` | No longer needed: the index is built automatically when missing. Still accepted so existing callers keep working. |

**Sample call:**

```json
{
  "query": ""
}
```

---

### `lookup_api_method`

Look up one SolidWorks API method or property: parameters, return type, description.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year` | `int?` | — | `None` | SolidWorks year whose API to answer for, e.g. 2026. Usually leave unset: the server's --year, else the newest installed. A year that isn't installed is explained in the result's note. |
| `index_file` | `str?` | — | `None` | Path to a saved index JSON to answer from instead of the installed type library, e.g. one copied from another machine. Rarely needed. |
| `interface` | `str` | ✅ | `` | COM interface name, e.g. 'IFeatureManager' or 'IModelDoc2' |
| `method` | `str` | ✅ | `` | Method or property name, e.g. 'InsertFeatureChamfer'; case does not matter |

**Sample call:**

```json
{
  "interface": "example",
  "method": "example"
}
```

---

### `lookup_api_interface`

List every method and property of a SolidWorks COM interface.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year` | `int?` | — | `None` | SolidWorks year whose API to answer for, e.g. 2026. Usually leave unset: the server's --year, else the newest installed. A year that isn't installed is explained in the result's note. |
| `index_file` | `str?` | — | `None` | Path to a saved index JSON to answer from instead of the installed type library, e.g. one copied from another machine. Rarely needed. |
| `interface` | `str` | ✅ | `` | COM interface name, e.g. 'ISldWorks'; case does not matter |

**Sample call:**

```json
{
  "interface": "example"
}
```

---

### `find_related_api_members`

Find SolidWorks API members related to an interface or member name.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year` | `int?` | — | `None` | SolidWorks year whose API to answer for, e.g. 2026. Usually leave unset: the server's --year, else the newest installed. A year that isn't installed is explained in the result's note. |
| `index_file` | `str?` | — | `None` | Path to a saved index JSON to answer from instead of the installed type library, e.g. one copied from another machine. Rarely needed. |
| `name` | `str` | ✅ | `` | An interface name (lists its members) or a member name (lists the members beside it), e.g. 'InsertSketch' |
| `max_results` | `int` | — | `25` | Maximum related members to return |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---
