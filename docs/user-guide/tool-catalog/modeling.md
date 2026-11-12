# Modeling Tools

Create and manipulate SolidWorks parts, assemblies, and drawings. These are the foundational tools for any CAD workflow — opening files, creating features (extrude, revolve), and querying/setting driven dimensions.

> **Prerequisite:** An active SolidWorks session. Most feature tools require an open Part document.

**Total tools in this category: 35**

---

### `open_model`

Open a part, assembly or drawing from disk and make it the active document.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Full path to the SolidWorks file (.sldprt, .sldasm, .slddrw) |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `create_part`

Create a new, empty part document and make it active, ready for `create_sketch`.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str` | ✅ | `` | A label for your own reference; SolidWorks names the new part itself (Part1, ...) and the file takes the name of the path you save it to with save_part |
| `template` | `str?` | — | `None` | Part template (.prtdot) path; omit to use the SolidWorks default |
| `units` | `str?` | — | `None` | Document units |
| `material` | `str?` | — | `None` | Material name |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---

### `create_assembly`

Create a new, empty assembly document and make it active, ready for `insert_component`.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str` | ✅ | `` | A label for your own reference; SolidWorks names the new assembly itself (Assem1, ...) and the file takes the name of the path you save it to with save_assembly |
| `template` | `str?` | — | `None` | Assembly template (.asmdot) path; omit to use the SolidWorks default |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---

### `create_drawing`

Create a new, empty drawing document and make it active.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str` | ✅ | `` | A label for your own reference; SolidWorks names the new drawing itself (Draw1, ...) and the file takes the name of the path you save it to with save_file |
| `template` | `str?` | — | `None` | Drawing template (.drwdot) path; omit to use the SolidWorks default |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---

### `close_model`

Close the active document, saving it first only if asked.

**Prerequisite:** An active open document

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `save` | `bool` | — | `False` | Save the model before closing |
| `overwrite_modified_references` | `bool` | — | `False` | Set true only after the user agreed: lets saving an assembly also overwrite the user's own modified part files that a `confirmation_required` error listed. |

**Sample call:**

```json
{}
```

---

### `create_extrusion`

Extrude the sketch you just closed into a solid boss, added to the active part.

**Prerequisite:** Active part with an active sketch (exit sketch first with exit_sketch)

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sketch_name` | `str?` | — | `None` | Sketch to use, by its name in the feature tree (e.g. "Sketch2"); omit to use the sketch `exit_sketch` closed last |
| `depth` | `float` | ✅ | `` | Extrusion depth in millimeters |
| `reverse` | `bool?` | — | `None` | Reverse direction alias |
| `draft_angle` | `float` | — | `0.0` | Draft angle in degrees |
| `reverse_direction` | `bool` | — | `False` | Reverse extrusion direction |
| `both_directions` | `bool` | — | `False` | Extrude symmetrically about the sketch plane (mid-plane): `depth` is the total thickness, half on each side |
| `thin_feature` | `bool` | — | `False` | Make a thin wall of `thin_thickness` from the sketch's outline; the sketch may be an open chain (a bent plate's centreline) |
| `thin_thickness` | `float?` | — | `None` | Wall thickness in mm; required with thin_feature |
| `thin_side` | `Literal['one_side', 'other_side', 'mid_plane']` | — | `one_side` | Which side of the sketch line the thin wall grows on: one_side, other_side, or mid_plane (half each side) |
| `end_condition` | `str` | — | `Blind` | End condition type |
| `merge_result` | `bool` | — | `True` | Merge with existing geometry |

**Sample call:**

```json
{
  "depth": 25.0
}
```

---

### `create_revolve`

Revolve a closed sketch around an axis, adding a solid to the active part.

**Prerequisite:** Active part with an active sketch containing the profile and axis

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sketch_name` | `str?` | — | `None` | Sketch to use, by its name in the feature tree (e.g. "Sketch2"); omit to use the sketch `exit_sketch` closed last |
| `axis_entity` | `str?` | — | `None` | A reference axis to revolve about, by its name in the feature tree (e.g. "Axis1" from `create_axis`); omit to use the centreline drawn in the sketch |
| `angle` | `float` | ✅ | `` | Revolve angle in degrees |
| `reverse_direction` | `bool` | — | `False` | Reverse revolve direction |
| `both_directions` | `bool` | — | `False` | Revolve in both directions |
| `thin_feature` | `bool` | — | `False` | Create as thin wall feature |
| `thin_thickness` | `float?` | — | `None` | Thickness for thin wall feature in mm |
| `merge_result` | `bool` | — | `True` | Merge with existing geometry |

**Sample call:**

```json
{
  "angle": 360.0
}
```

---

### `get_dimension`

Read one dimension of the active model by its full name, e.g. "D1@Sketch1".

**Prerequisite:** Active document with named dimensions

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str?` | — | `None` | Dimension name (e.g., 'D1@Sketch1', 'D1@Boss-Extrude1') |
| `dimension_name` | `str?` | — | `None` | Dimension name alias |

**Sample call:**

```json
{}
```

---

### `set_dimension`

Change one dimension of the active model and rebuild.

**Prerequisite:** Active document with named dimensions

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str?` | — | `None` | Dimension name (e.g., 'D1@Sketch1', 'D1@Boss-Extrude1') |
| `dimension_name` | `str?` | — | `None` | Dimension name alias |
| `value` | `float` | ✅ | `` | New value in the dimension's own unit: millimetres for a length, degrees for an angle, a whole number for a count (a pattern's instances). list_model_dimensions gives each one's `units`. |
| `units` | `str?` | — | `None` | Not used; kept for old callers |

**Sample call:**

```json
{
  "value": 50.0
}
```

---

### `set_units`

Set the active document's length units: mm, cm, m, in or ft.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `unit_system` | `str` | ✅ | `` | Linear unit system: mm, cm, m, in, or ft |

**Sample call:**

```json
{
  "unit_system": "example"
}
```

---

### `create_cut_extrude`

Cut material from the active part with a closed sketch profile: holes, slots, windows.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `depth` | `float` | ✅ | `` | Cut depth in millimeters |
| `draft_angle` | `float` | — | `0.0` | Draft angle in degrees |
| `reverse_direction` | `bool?` | — | `None` | Usually leave unset: a one-way cut then tries both sides of the sketch and keeps the one that removes more material (on a tie, the side along the sketch normal, where create_extrusion grows). true cuts along the sketch normal, the side create_extrusion grows into by default; false cuts against it (from a sketch on a face, into the part). A set side that has no material is cut the other way instead, and the reply sets direction_flipped |
| `end_condition` | `str` | — | `Blind` | 'Blind' (cut 'depth' mm), 'ThroughAll' (through the body, one way) or 'ThroughAllBoth' (through the body both ways, for a sketch inside the body) |
| `both_directions` | `bool` | — | `False` | With end_condition 'ThroughAll', cut through the body both ways (same as 'ThroughAllBoth') |
| `sketch_name` | `str?` | — | `None` | Sketch to cut from, e.g. 'Sketch3'. If omitted, the sketch most recently created/exited in this session is used, but only if it still exists in the model — there is no other fallback. Pass this explicitly whenever more than one unconsumed sketch could exist, or after any operation that might have changed the active sketch. |

**Sample call:**

```json
{
  "depth": 25.0
}
```

---

### `add_fillet`

Round edges of the active part with a constant-radius fillet.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `radius` | `float` | ✅ | `` | Fillet radius in millimeters |
| `edge_names` | `List[str]` | ✅ | `` | Edges (or faces) to fillet. Accepts a topology name (e.g. 'Edge<1>'), a coordinate hint in metres ('x,y,z') to select the nearest edge, or 'face:x,y,z' to select a whole face — which fillets every edge bounding it in one call. Prefer 'face:' over a coordinate on an edge that sits exactly on a shared boundary between two faces (e.g. a hole rim flush with a flat face): the nearest-edge match there can silently resolve to a different, unrelated edge. Leave empty to use whatever is *currently selected* in the live SolidWorks UI (e.g. entities read back via get_selected_entities and left selected) without touching the selection — this is the most reliable option when the user has hand-picked specific edges, since it never round-trips through coordinates. Falls back to filleting all edges only if nothing at all is selected. |

**Sample call:**

```json
{
  "radius": 15.0,
  "edge_names": "MCP_Demo_Part"
}
```

---

### `add_chamfer`

Bevel edges of the active part with a chamfer: `distance` along one face at `angle` (45 by default).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `distance` | `float` | ✅ | `` | Chamfer distance in millimeters, along one of the edge's faces |
| `angle` | `float` | — | `45.0` | Chamfer angle in degrees, between 0 and 90; 45 makes both legs equal to distance |
| `flip` | `bool` | — | `False` | Measure distance along the edge's other face (swaps the long and short legs of an angled chamfer) |
| `edge_names` | `List[str]` | ✅ | `` | Edges (or faces) to chamfer. Accepts a topology name (e.g. 'Edge<1>'), a coordinate hint in metres ('x,y,z') to select the nearest edge, or 'face:x,y,z' to select a whole face — which chamfers every edge bounding it in one call. Prefer 'face:' over a coordinate on an edge that sits exactly on a shared boundary between two faces (e.g. a hole rim flush with a flat face): the nearest-edge match there can silently resolve to a different, unrelated edge. Leave empty to use whatever is *currently selected* in the live SolidWorks UI (e.g. entities read back via get_selected_entities and left selected) without touching the selection — this is the most reliable option when the user has hand-picked specific edges, since it never round-trips through coordinates. Falls back to chamfering all edges only if nothing at all is selected. |

**Sample call:**

```json
{
  "distance": 10.0,
  "edge_names": "MCP_Demo_Part"
}
```

---

### `create_sweep`

Sweep a closed profile sketch along a path sketch to make a solid (Insert > Boss/Base > Sweep).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `str` | ✅ | `` | Name or ID of the sweep path |
| `twist_along_path` | `bool` | — | `False` | Twist along path |
| `twist_angle` | `float` | — | `0.0` | Twist angle in degrees |
| `merge_result` | `bool` | — | `True` | Merge with existing geometry |

**Sample call:**

```json
{
  "path": "C:\\Temp\\mcp_demo\\file.sldprt"
}
```

---

### `create_loft`

Loft a solid through two or more closed profile sketches, in order (Insert > Boss/Base > Loft).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `profiles` | `List[str]` | ✅ | `` | List of profile names or IDs |
| `guide_curves` | `List[str]?` | — | `None` | List of guide curve names or IDs |
| `start_tangent` | `str?` | — | `None` | Start tangent condition |
| `end_tangent` | `str?` | — | `None` | End tangent condition |
| `merge_result` | `bool` | — | `True` | Merge with existing geometry |

**Sample call:**

```json
{
  "profiles": [
    "Sketch1",
    "Sketch2"
  ]
}
```

---

### `insert_component`

Insert a part or sub-assembly file into the active assembly with its origin at a point in mm.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | `str` | ✅ | `` | Absolute path to the .sldprt or .sldasm to insert |
| `x` | `float` | — | `0.0` | X position in millimetres |
| `y` | `float` | — | `0.0` | Y position in millimetres |
| `z` | `float` | — | `0.0` | Z position in millimetres |

**Sample call:**

```json
{
  "file_path": "C:\\Temp\\mcp_demo\\part.sldprt"
}
```

---

### `add_mate`

Mate two components of the active assembly: coincident, concentric, parallel, perpendicular, tangent, distance or angle.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `component_a` | `str` | ✅ | `` | First component instance name, as reported by list_components |
| `component_b` | `str` | ✅ | `` | Second component instance name |
| `entity_a` | `str?` | — | `None` | Named reference plane or axis on the first component, e.g. 'Front Plane'; defaults to 'Front Plane' when face_a is not given either |
| `entity_b` | `str?` | — | `None` | Named reference plane or axis on the second component; defaults to 'Front Plane' when face_b is not given either |
| `face_a` | `List[float]?` | — | `None` | [x, y, z] in mm on a face of the first component, in that part's own coordinates (as it was modelled), instead of entity_a: e.g. a point on a pin's round face for a concentric mate |
| `face_b` | `List[float]?` | — | `None` | [x, y, z] in mm on a face of the second component, in its own part coordinates, instead of entity_b |
| `mate_type` | `str` | — | `coincident` | coincident, concentric, perpendicular, parallel, tangent, distance or angle |
| `alignment` | `str` | — | `aligned` | aligned, anti_aligned or closest |
| `distance` | `float` | — | `0.0` | Distance in millimetres, for a distance mate |
| `angle` | `float` | — | `0.0` | Angle in degrees, for an angle mate |

**Sample call:**

```json
{
  "component_a": "example",
  "component_b": "example"
}
```

---

### `set_component_state`

Fix or float a component of the active assembly, or make a sub-assembly rigid or flexible.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `component` | `str` | ✅ | `` | Component instance name, as reported by list_components |
| `fixed` | `bool?` | — | `None` | true fixes the component in place; false floats it so mates can move it; leave it out to keep it as it is |
| `flexible` | `bool?` | — | `None` | For a sub-assembly: true lets its own mates move inside this assembly (a crank that turns); false makes it rigid; leave it out to keep it as it is |

**Sample call:**

```json
{
  "component": "example"
}
```

---

### `list_components`

List the top-level components of the active assembly by instance name, e.g. "bracket-1".

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `delete_feature`

Delete a feature or sketch from the active model, along with the features that depend on it.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str` | ✅ | `` | Feature or sketch name, e.g. 'Boss-Extrude1' or 'Sketch1' |
| `delete_absorbed` | `bool` | — | `False` | Delete the feature's own sketch too (a cut's profile); off leaves it in the tree and the reply names it |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---

### `suppress_feature`

Suppress or unsuppress a feature of the active model; suppressed features stay in the tree but are not built.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str` | ✅ | `` | Feature name, e.g. 'Fillet1' |
| `suppress` | `bool` | — | `True` | True to suppress, False to unsuppress |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---

### `rename_feature`

Rename a feature in the active model's feature tree.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `old_name` | `str` | ✅ | `` | Current feature name, e.g. 'Fillet1' |
| `new_name` | `str` | ✅ | `` | New feature name, e.g. 'MountingEdgeFillet' |

**Sample call:**

```json
{
  "old_name": "MCP_Demo_Part",
  "new_name": "MCP_Demo_Part"
}
```

---

### `select_feature`

Select a feature, sketch, plane or component by name in the active document.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `feature_name` | `str` | ✅ | `` | Feature, sketch, plane or component name, e.g. 'Boss-Extrude1', 'Sketch1', 'Front Plane' (an '@Part1' suffix is ok) |
| `append` | `bool` | — | `False` | Add to the current selection instead of replacing it |

**Sample call:**

```json
{
  "feature_name": "MCP_Demo_Part"
}
```

---

### `select_face_edges`

Select every edge of one face of the active part, ready for `add_fillet` or `add_chamfer` with no edge names.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `point` | `List[float]?` | — | `None` | A point on the face, [x, y, z] in mm |
| `side` | `str?` | — | `None` | Outward direction of the face: +X/-X/+Y/-Y/+Z/-Z or right/left/top/bottom/front/back (top=+Y, front=+Z, right=+X, as in SolidWorks' default views); picks the furthest flat face that way |
| `plane` | `str?` | — | `None` | Reference plane name, e.g. 'Front Plane'; picks the body face(s) lying on it |
| `edge_type` | `str` | — | `all` | 'all', 'linear' or 'circular' (e.g. hole rims) |
| `append` | `bool` | — | `False` | Add to the current selection instead of replacing it |

**Sample call:**

```json
{}
```

---

### `select_edges`

Select the edges of the active part that match rules, ready for `add_fillet` or `add_chamfer` with no edge names.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `feature` | `str?` | — | `None` | Take the edges of the faces this feature made, e.g. 'Cut-Extrude2' (the cut's walls and rims). Give at most one of feature, face_point, side and plane; none takes every edge of the part |
| `face_point` | `List[float]?` | — | `None` | Take the edges of the face at this point, [x, y, z] mm |
| `side` | `str?` | — | `None` | Take the edges of the furthest flat face facing this way: top, bottom, front, back, right, left or +X..-Z |
| `plane` | `str?` | — | `None` | Take the edges of the face(s) lying on this plane, e.g. 'Top Plane' |
| `edge_type` | `str` | — | `all` | Keep 'all' (the default), 'linear' or 'circular' edges |
| `parallel_to` | `str | List[float]?` | — | `None` | Keep only straight edges along this direction: 'x', 'y', 'z' or [x, y, z] |
| `parallel_tolerance_deg` | `float` | — | `1.0` | How many degrees off parallel_to an edge may be (default 1) |
| `inside_box` | `List[List[float]]?` | — | `None` | Keep only edges wholly inside this box: [[xmin, ymin, zmin], [xmax, ymax, zmax]] in model mm |
| `min_length` | `float?` | — | `None` | Keep only edges at least this long, mm |
| `max_length` | `float?` | — | `None` | Keep only edges at most this long, mm |
| `any_of` | `List[Dict[str, Any]]?` | — | `None` | Several rules in one call: select the edges any of them matches. Each rule takes the keys above (a source and filters) and is laid over the ones given outside any_of, e.g. {'feature': 'Boss-Extrude1', 'any_of': [{'inside_box': [[0,0,0],[5,5,5]]}, {'inside_box': [[20,0,0],[25,5,5]]}]}. Each source's edges are read once, so this is much faster than one call per rule |
| `append` | `bool` | — | `False` | Add to the current selection instead of replacing it |

**Sample call:**

```json
{}
```

---

### `set_visibility`

Show or hide planes, axes, points, origins and sketches in the active document.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `visible` | `bool` | ✅ | `` | true shows them, false hides them |
| `names` | `List[str]` | ✅ | `` | Planes, axes, points, coordinate systems or sketches by their tree names, e.g. ['Plane1', 'Sketch3'] |
| `types` | `List[DisplayType]` | ✅ | `` | Every entity of these types in the document, as View > Hide/Show does: planes, axes, temporary_axes, origins, coordinate_systems, points, sketches |

**Sample call:**

```json
{
  "visible": false,
  "names": "MCP_Demo_Part",
  "types": []
}
```

---

### `edit_feature`

Change an existing feature's parameters in place: an extrude's or cut's depth, end condition or direction, a revolve's angle, a fillet's radius.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str` | ✅ | `` | The feature to change, e.g. 'Cut-Extrude2' |
| `depth` | `float?` | — | `None` | Extrude or cut: the new depth, mm |
| `end_condition` | `str?` | — | `None` | Extrude or cut: Blind, ThroughAll, ThroughAllBoth, MidPlane or UpToNext |
| `reverse_direction` | `bool?` | — | `None` | Extrude, cut or revolve: true to go the other way |
| `angle` | `float?` | — | `None` | Revolve: the new angle, degrees |
| `radius` | `float?` | — | `None` | Fillet: the new radius, mm |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---

### `set_rollback`

Move the rollback bar before or after a feature, so new features go in there, or back to the end.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `before` | `str?` | — | `None` | Put the bar just above this feature, e.g. 'Fillet1' |
| `after` | `str?` | — | `None` | Put the bar just below this feature; neither moves it to the end |

**Sample call:**

```json
{}
```

---

### `rebuild_model`

Rebuild the active model and report each feature that fails, with the reason and a fix.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `top_level_only` | `bool` | — | `False` | Rebuild only the top level of an assembly (default: full rebuild including sub-assemblies) |

**Sample call:**

```json
{}
```

---

### `undo`

Undo the last operations in the active model (Edit > Undo).

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `count` | `int` | — | `1` | Number of operations to undo |

**Sample call:**

```json
{}
```

---

### `create_reference_plane`

Add a reference plane offset from, at an angle to, or on a plane or flat face.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `reference` | `str` | — | `` | Name of the reference plane, e.g. 'Front Plane' or 'Plane1'; leave it out when giving face_point |
| `face_point` | `List[float]?` | — | `None` | [x, y, z] in mm on a flat face of the part (sloped or not), to use that face as the reference instead of a named plane |
| `offset` | `float` | — | `0.0` | Offset distance in millimetres. Non-zero for a named plane; 0 with face_point puts the plane on the face |
| `angle` | `float` | — | `0.0` | Angle in degrees between the new plane and the reference, about axis |
| `axis` | `str?` | — | `None` | Name of the axis the plane rotates about, e.g. 'Axis1' from create_axis; required with angle |
| `flip` | `bool` | — | `False` | Reverse the offset side or the angle direction |

**Sample call:**

```json
{}
```

---

### `create_axis`

Add a reference axis along the model's x, y or z direction, through the origin.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `reference` | `str` | ✅ | `` | Principal axis direction: 'x', 'y' or 'z' (case-insensitive; a leading +/- is stripped) |

**Sample call:**

```json
{
  "reference": "example"
}
```

---

### `create_reference_point`

Add a reference point on an edge (at a distance or percentage along it) or at the centre of a face.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `mode` | `str` | ✅ | `` | 'along_curve' (a point on an edge) or 'face_center' (the centroid of a face) |
| `x` | `float` | ✅ | `` | X of a point on the target edge/face, in mm |
| `y` | `float` | ✅ | `` | Y of a point on the target edge/face, in mm |
| `z` | `float` | ✅ | `` | Z of a point on the target edge/face, in mm |
| `distance` | `float?` | — | `None` | along_curve only: offset from the edge start in mm (give exactly one of distance or percent) |
| `percent` | `float?` | — | `None` | along_curve only: position as 0-100 of the edge length |

**Sample call:**

```json
{
  "mode": "example",
  "x": 10.0,
  "y": 10.0,
  "z": 10.0
}
```

---

### `mirror_feature`

Mirror solid bodies or features of the active part about a plane.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `features` | `List[str]` | ✅ | `` | Body or feature names to mirror. At least one required. For a body mirror these are the names as they appear under Solid Bodies, which for a lofted wing is the loft's own name |
| `mirror_plane` | `str` | ✅ | `` | Plane name to mirror about, e.g. 'Right Plane' |
| `merge` | `bool` | — | `True` | Merge the mirrored result with the original body |
| `mirror_bodies` | `bool` | — | `True` | Mirror whole solid bodies rather than individual features. Defaults to True, which is what works for anything built from a loft or sweep - a feature mirror only resolves when the feature's own sketch sits on the mirror plane |

**Sample call:**

```json
{
  "features": [],
  "mirror_plane": "example"
}
```

---

### `pattern_circular`

Repeat features of the active part around an axis, e.g. a ring of bosses or ribs.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `features` | `List[str]` | ✅ | `` | Names of the features to pattern. At least one required. |
| `axis` | `str` | ✅ | `` | Name of the axis to rotate about, e.g. 'Axis1' as created by create_axis |
| `count` | `int` | ✅ | `` | Total number of instances including the original. Must be at least 2 - a pattern of one is just the original feature |
| `angle` | `float?` | — | `None` | Total angle in degrees the instances are spread over evenly; a full 360 when neither angle nor step_angle is given |
| `step_angle` | `float?` | — | `None` | Instead of angle: degrees between neighbouring instances, e.g. 60 for instances every 60 degrees |
| `reverse_direction` | `bool` | — | `False` | Pattern the other way round the axis |

**Sample call:**

```json
{
  "features": [],
  "axis": "example",
  "count": 10.0
}
```

---
