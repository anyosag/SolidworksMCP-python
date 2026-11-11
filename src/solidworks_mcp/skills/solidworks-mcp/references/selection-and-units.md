# Selection and units

## Units, tool by tool

Millimetres and degrees everywhere, except:

| Takes or returns metres | What |
| --- | --- |
| `add_fillet`, `add_chamfer` | the `"x,y,z"` and `"face:x,y,z"` specs in `edge_names` |
| `measure_entities` | the entity coordinates you pass, and `distance_m`, `length_m`, `area_m2` and the other results |
| `list_model_dimensions` | `system_value` (metres or radians); `value` is in the document's units |

Points in mm, for contrast: `select_face_edges` `point`,
`create_reference_point` `x`/`y`/`z`, `insert_component` `x`/`y`/`z`, and
the sketch tools. `get_selected_entities` reports in mm (`center_mm`,
`length_mm`).

`set_dimension` takes millimetres and is for lengths; don't use it on an
angle dimension. `set_units` changes what the document shows, not what the
tools take.

Mass is in kg, volume in mm³. `calculate_mass_properties` returns moments
of inertia in kg·mm², about the centre of mass.

## Planes and model axes

| Sketch plane | Also called | Sketch x, sketch y in the model | Extrudes along | `select_face_edges` side facing that way |
| --- | --- | --- | --- | --- |
| Front | XY | +X, +Y | z | front (+Z) / back (-Z) |
| Top | XZ | +X, **-Z** | y | top (+Y) / bottom (-Y) |
| Right | YZ | **-Z**, +Y | x | right (+X) / left (-X) |

`verify_model`'s `bounding_box_mm` is [x, y, z] in these axes, so a
100 x 60 rectangle on the Top plane extruded 10 mm is [100, 10, 60], and a
point at sketch (10, 20) on Top is model (10, 0, -20).

`create_sketch` returns `sketch.axes` for the plane it used: `x`, `y` and
`normal` as model vectors, the sketch origin in mm, and a `summary` such as
"sketch x = model +X, sketch y = model -Z, normal = model +Y". It is read
from the sketch itself, so it is right for a plane made by
`create_reference_plane` too.

Any plane name `create_reference_plane` returned works in `create_sketch`. A
name that isn't in the part is a `not_found` error; it is never swapped for
another plane.

## Picking faces and edges

In order of reliability:

1. **The user's selection.** When they point at something, call
   `get_selected_entities` and use what it reports. `add_fillet` and
   `add_chamfer` with empty `edge_names` act on the current selection.
2. **`select_face_edges`.** Every edge of one face, by `side` (the furthest
   flat face that way), a `point` on the face in mm, or a `plane` the face
   lies on. `edge_type: "circular"` picks hole rims, `"linear"` the straight
   edges. Then fillet or chamfer with empty `edge_names`.
3. **A face spec.** `"face:x,y,z"` (metres) in `edge_names` treats every edge
   of the face containing that point.
4. **An edge point.** `"x,y,z"` (metres) picks the nearest edge. Avoid it
   where two faces meet at the point (a hole rim on a flat face): it can
   pick a different edge.

Selection is fragile: anything that selects or rebuilds in between clears
it, including `calculate_mass_properties`, `rebuild_model`,
`measure_entities`, and `verify_model` when it checks `mass_kg`. Select immediately before the tool that uses it.

`select_feature` selects a feature, sketch, plane or component by name, for
the tools that act on a selection.

## Sketch entities

Each sketch tool returns an `id` (e.g. "Line_1"); `add_outlines` returns one
per segment. `add_sketch_constraint`, `add_sketch_dimension`,
`sketch_mirror`, `sketch_offset` and the sketch patterns take these ids.
`check_sketch_fully_defined` says whether the sketch still has free geometry.

Arcs run counter-clockwise from start to end, looking at the sketch with x
right and y up; give `direction: "cw"` for the other way round.
`construction: true` on `add_line`, `add_circle`, `add_rectangle` or an
outline draws construction geometry, which a feature ignores.
