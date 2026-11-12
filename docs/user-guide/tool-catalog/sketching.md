# Sketching Tools

Build 2-D sketch geometry (lines, circles, arcs, splines, polygons) and apply geometric constraints and driven dimensions. Sketches are the prerequisite for every extrusion, revolve, sweep, and loft feature.

> **Prerequisite:** An active part document with an active sketch edit session.

**Total tools in this category: 22**

---

### `create_sketch`

Open a new sketch on a plane of the active part, ready for lines, circles and other sketch entities.

**Prerequisite:** Active part document, no active sketch

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `plane` | `str` | ✅ | `` | Plane to sketch on: 'Front' (or 'XY'), 'Top' ('XZ'), 'Right' ('YZ'), or the exact name of a plane in the part, e.g. 'Plane1' |
| `sketch_name` | `str?` | — | `None` | Name to give the sketch in the feature tree, applied when exit_sketch closes it; omit to keep SolidWorks' own (Sketch1, Sketch2, ...) |

**Sample call:**

```json
{
  "plane": "Front"
}
```

---

### `add_line`

Draw a straight line between two points in the open sketch, in mm.

**Prerequisite:** Active sketch edit mode

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `x1` | `float?` | — | `None` | Start point X coordinate in mm |
| `y1` | `float?` | — | `None` | Start point Y coordinate in mm |
| `x2` | `float?` | — | `None` | End point X coordinate in mm |
| `y2` | `float?` | — | `None` | End point Y coordinate in mm |
| `start_x` | `float?` | — | `None` | Start point X alias |
| `start_y` | `float?` | — | `None` | Start point Y alias |
| `end_x` | `float?` | — | `None` | End point X alias |
| `end_y` | `float?` | — | `None` | End point Y alias |
| `construction` | `bool` | — | `False` | Construction geometry flag |

**Sample call:**

```json
{}
```

---

### `add_circle`

Draw a circle in the open sketch from its centre and radius, in mm.

**Prerequisite:** Active sketch edit mode

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `center_x` | `float` | ✅ | `` | Circle center X coordinate in mm |
| `center_y` | `float` | ✅ | `` | Circle center Y coordinate in mm |
| `radius` | `float` | ✅ | `` | Circle radius in mm |
| `construction` | `bool` | — | `False` | Construction geometry flag |

**Sample call:**

```json
{
  "center_x": 0.0,
  "center_y": 0.0,
  "radius": 15.0
}
```

---

### `add_rectangle`

Draw a closed, axis-aligned rectangle in the open sketch from two opposite corners, in mm.

**Prerequisite:** Active sketch edit mode

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `x1` | `float?` | — | `None` | First corner X coordinate in mm |
| `y1` | `float?` | — | `None` | First corner Y coordinate in mm |
| `x2` | `float?` | — | `None` | Opposite corner X coordinate in mm |
| `y2` | `float?` | — | `None` | Opposite corner Y coordinate in mm |
| `corner1_x` | `float?` | — | `None` | Corner 1 X alias |
| `corner1_y` | `float?` | — | `None` | Corner 1 Y alias |
| `corner2_x` | `float?` | — | `None` | Corner 2 X alias |
| `corner2_y` | `float?` | — | `None` | Corner 2 Y alias |
| `construction` | `bool` | — | `False` | Construction geometry flag |

**Sample call:**

```json
{}
```

---

### `exit_sketch`

Close the open sketch so a feature can use it.

**Prerequisite:** Active sketch edit mode

**Sample call:**

```json
{}
```

---

### `check_sketch_fully_defined`

Check whether a sketch is fully defined, under-defined or over-defined.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sketch_name` | `str?` | — | `None` | Optional sketch name. If omitted, checks the active or last sketch. |

**Sample call:**

```json
{}
```

---

### `add_arc`

Draw a circular arc in the open sketch from its centre, start point and end point, in mm.

**Prerequisite:** Active sketch edit mode

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `center_x` | `float` | ✅ | `` | Arc center X coordinate in mm |
| `center_y` | `float` | ✅ | `` | Arc center Y coordinate in mm |
| `start_x` | `float` | ✅ | `` | Arc start point X coordinate in mm |
| `start_y` | `float` | ✅ | `` | Arc start point Y coordinate in mm |
| `end_x` | `float` | ✅ | `` | Arc end point X coordinate in mm |
| `end_y` | `float` | ✅ | `` | Arc end point Y coordinate in mm |
| `direction` | `Literal['ccw', 'cw']` | — | `ccw` | Which way the arc runs from start to end, looking at the sketch (x right, y up): 'ccw' counter-clockwise (the default) or 'cw' |

**Sample call:**

```json
{
  "center_x": 0.0,
  "center_y": 0.0,
  "start_x": -30.0,
  "start_y": 0.0,
  "end_x": 30.0,
  "end_y": 0.0
}
```

---

### `add_outlines`

Draw whole outlines of lines and arcs in the open sketch in one call, in mm.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `outlines` | `List[Outline]` | ✅ | `` | One or more outlines, each a closed loop by default. Give each either 'points' (a polygon) or 'start' plus 'segments' (lines and arcs) |

**Sample call:**

```json
{
  "outlines": []
}
```

---

### `edit_sketch`

Open an existing sketch for editing, listing its segments with ids.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | `str` | ✅ | `` | The sketch to open, e.g. 'Sketch3' |

**Sample call:**

```json
{
  "name": "MCP_Demo_Part"
}
```

---

### `delete_sketch_entities`

Delete lines, arcs and other entities of the open sketch by id, or all of them.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `ids` | `List[str]?` | — | `None` | Ids of the entities to delete, from the latest edit_sketch reply or the add_* tools since (ids change each time a sketch is opened) |
| `all` | `bool` | — | `False` | true deletes every entity of the open sketch, ids or not; give it instead of ids |

**Sample call:**

```json
{}
```

---

### `add_spline`

Draw a smooth spline through a list of points in the open sketch, in mm.

**Prerequisite:** Active sketch edit mode

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `points` | `List[Dict[str, float]]` | ✅ | `` | List of spline control points with x, y coordinates |

**Sample call:**

```json
{
  "points": [
    {
      "x": 0.0,
      "y": 0.0
    },
    {
      "x": 10.0,
      "y": 15.0
    },
    {
      "x": 20.0,
      "y": 10.0
    }
  ]
}
```

---

### `add_centerline`

Draw a centreline (construction line) in the open sketch, in mm.

**Prerequisite:** Active sketch edit mode

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `x1` | `float?` | — | `None` | Start point X coordinate in mm |
| `y1` | `float?` | — | `None` | Start point Y coordinate in mm |
| `x2` | `float?` | — | `None` | End point X coordinate in mm |
| `y2` | `float?` | — | `None` | End point Y coordinate in mm |
| `start_x` | `float?` | — | `None` | Start point X alias |
| `start_y` | `float?` | — | `None` | Start point Y alias |
| `end_x` | `float?` | — | `None` | End point X alias |
| `end_y` | `float?` | — | `None` | End point Y alias |
| `construction` | `bool` | — | `False` | Construction geometry flag |

**Sample call:**

```json
{}
```

---

### `add_polygon`

Draw a regular polygon (e.g. a hexagon) in the open sketch from its centre, radius and number of sides.

**Prerequisite:** Active sketch edit mode

**Sample call:**

```json
{}
```

---

### `add_ellipse`

Draw an ellipse in the open sketch from its centre and axis lengths, in mm.

**Prerequisite:** Active sketch edit mode

**Sample call:**

```json
{}
```

---

### `add_sketch_constraint`

Add a geometric relation between sketch entities: horizontal, vertical, parallel, perpendicular, tangent, coincident, concentric, equal, symmetric, collinear or fix.

**Prerequisite:** Active sketch edit mode with named entities

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `entity1` | `str` | ✅ | `` | First entity name or ID |
| `entity2` | `str?` | — | `None` | Second entity name or ID (if required) |
| `entity3` | `str?` | — | `None` | Third entity ID. Required for 'symmetric' (the centerline of symmetry); must be null for all other relations. |
| `relation_type` | `str` | ✅ | `` | Relation type (parallel, perpendicular, tangent, coincident, etc.) |

**Sample call:**

```json
{
  "entity1": "Line1",
  "relation_type": "perpendicular"
}
```

---

### `add_sketch_dimension`

Add a driving dimension to sketch entities: linear, angular, radial or diameter.

**Prerequisite:** Active sketch edit mode

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `entity1` | `str` | ✅ | `` | First entity name or ID |
| `entity2` | `str?` | — | `None` | Second entity name or ID (for distance dimensions) |
| `dimension_type` | `str` | — | `linear` | Dimension type (linear, radial, angular, etc.) |
| `value` | `float` | ✅ | `` | Dimension value in mm or degrees |

**Sample call:**

```json
{
  "entity1": "Line1",
  "value": 50.0
}
```

---

### `sketch_linear_pattern`

Repeat sketch entities in a straight line at a fixed spacing.

**Prerequisite:** Active sketch edit mode

**Sample call:**

```json
{}
```

---

### `sketch_circular_pattern`

Repeat sketch entities around the sketch origin, e.g. a bolt circle.

**Prerequisite:** Active sketch edit mode

**Sample call:**

```json
{}
```

---

### `sketch_mirror`

Mirror sketch entities about a centreline in the open sketch.

**Prerequisite:** Active sketch edit mode

**Sample call:**

```json
{}
```

---

### `sketch_offset`

Offset sketch entities by a distance in mm, outward or inward, e.g. for a wall or a clearance.

**Prerequisite:** Active sketch edit mode

**Sample call:**

```json
{}
```

---

### `sketch_tutorial_simple_hole`

Demonstrate the sketch steps: draw a 5 mm circle at the origin on the Top plane and close the sketch.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---

### `tutorial_simple_hole`

Draw a circle on a plane and cut it as a hole, as one worked example.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `plane` | `str` | ✅ | `` | Sketch plane for the hole |
| `center_x` | `float` | ✅ | `` | Hole center X coordinate in mm |
| `center_y` | `float` | ✅ | `` | Hole center Y coordinate in mm |
| `diameter` | `float` | ✅ | `` | Hole diameter in mm |
| `depth` | `float?` | — | `None` | Hole depth in mm (None for through hole) |

**Sample call:**

```json
{
  "plane": "Front",
  "center_x": 0.0,
  "center_y": 0.0,
  "diameter": 10.0
}
```

---
