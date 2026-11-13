## Context

`dishrack-fixes` already has the pieces this change builds on:
- `adapters/solidworks/placement.py` moves an inserted component's origin with `IComponent2.Transform2`, floating and fixing it around the move.
- `edge_rules.match_rules` reads each source's edges once.
- `feature_editing.edit_feature` changes a fillet's radius through `GetDefinition` / `AccessSelections` / `ModifyDefinition`.
- `utils/stl_mesh.py` reads an STL and welds its vertices.
- `export_stl_with_settings` sets the STL options for one export and puts the user's back, tolerances included.

The SolidWorks 2026 type library (gen_py) has what each request needs:
- `IModelDoc2.ClosestDistance(obj1, obj2, pt1, pt2)`;
- `IEntity.GetDistance(base, min, param, pos1, pos2, dist)`;
- `IMeasure`;
- `IModelDocExtension.CreateSectionViewData` with `IModelViewManager.CreateSectionView(data)`, where `ISectionViewData` has `FirstPlane`, `FirstOffset`, `FirstReverseDirection` and `ShowSectionCap`;
- `ISimpleFilletFeatureData2.Edges` and `IChamferFeatureData2.Edges`, both settable.

The API help warns that `ClosestDistance` measures a cylindrical face from its axis. A pin in a hole would then read 0 instead of the radial clearance. That alone rules it out for clearances unless a probe shows otherwise.

Every COM call stays on the connect thread through `_handle_com_operation`. New dispatch objects get their methods flagged before use (CLAUDE.md, method flagging; pitfalls #41, #42).

## Goals / Non-Goals

**Goals:**
- An agent can place, rotate, fix and float a component in one call, and see the transform read back.
- An agent can measure the gap between two components, see where it is, and picture a section through it.
- An agent can check a part for resin printing in a given orientation before exporting it.
- An agent can repair a fillet or chamfer whose edges an upstream edit removed, without deleting it.

**Non-Goals:**
- Mates (list, edit, delete): the Cellvis session ranked them low.
- Printing simulation: no slicing, no support generation, no peel forces. The check is geometric.
- Clearances between faces of one part, or between more than two components at once.
- Variable-radius, face and full-round fillets: edge sets of constant-radius fillets and chamfers only.

## Decisions

### D1. One placement function for insert and set

`placement.place(adapter, model, assembly, component, origin_m, rotation_rows=None, fixed=None)` replaces `place_origin`.
- With `rotation_rows=None` it keeps the current rotation (today's behaviour).
- It floats a fixed component for the move, and then leaves it in the state `fixed` asks for, or as it was.
- It reads `Transform2` back and returns `placed`, `transform` and `fixed`.

`insert_component` and `set_component_transform` both call it.

`IMathTransform.ArrayData` holds the 3×3 rotation as rows, then the translation in metres, then a scale. The spec's convention follows it: a point transforms as `p · R + t`, so each row of `R` is a component axis in assembly coordinates. `rotation_deg` is turned into rows in pure Python: `R = Rx · Ry · Rz` in row-vector form, applied about the assembly's X, then Y, then Z axis. Probe 3 confirmed it (2026-11-13): after the quarter turn about Y, a 20 x 6 x 10 block's `IComponent2.GetBox` in the assembly was exactly the box the row convention predicts.

**Alternative rejected:** `IComponent2.SetTransformAndSolve2`. It solves mates as it moves, so a mated component jumps somewhere unasked. Putting `Transform2` and reading it back makes a refused move visible as `placed: false`.

### D2. Clearance: face pairs, nearest boxes first

`clearance.py` walks the two components' solid bodies in assembly context:
- `IComponent2.GetBodies2(swSolidBody)`;
- each body's `GetFaces()`, and each face's assembly-context twin `IComponent2.GetCorrespondingEntity(face)`;
- each face's `GetBox()` turned into assembly coordinates by the component's transform. `GetBox` gives the part's own coordinates, on the twin too, and pads a plane by about 0.15 mm, so the box distance is a lower bound, as it should be.

The search runs as follows:
1. Order the face pairs by the distance between their boxes, a lower bound on the faces' distance.
2. Measure pairs in that order, keeping the best.
3. Stop when the next pair's lower bound is above the best found.

A dish-rack latch (around 40 faces each side) then needs tens of measurements, not 1600. `pairs_checked` reports how many were measured.

The measuring call is `IModelDoc2.ClosestDistance` on the twins, settled by **probe 1**. On a Ø9.5 pin in a Ø10 hole it gave 0.25 mm between points on the two surfaces, not the axes, despite the API help's warning. On a tongue in a slot it also gave 0.25 mm. Its points come in assembly coordinates. `IEntity.GetDistance` (min) returned 0 for faces that don't touch, so it is not used. `IMeasure.Calculate` on the two components agreed (0.25 mm both times), and is not needed.

A distance at or under 1e-6 mm is `touching: true`.

### D3. Section: on for one picture, off in a finally

`export_image`'s screenshot operation gains a step between turning to the view and zooming:
1. It finds the plane by name (`FeatureByName`, then `GetSpecificFeature2`, the `IRefPlane`).
2. It builds `ISectionViewData` with `FirstPlane`, `FirstOffset` in metres, `FirstReverseDirection` and `ShowSectionCap = True`.
3. It calls `ModelViewManager.CreateSectionView(data)`; the data comes from `ModelViewManager.CreateSectionViewData()`.

The removal, `ModelViewManager.RemoveSectionView()` (flagged: it takes no arguments), runs in the same `finally` that shows hidden types again. **Probe 2** confirmed both: the section changed 22.5% of the picture's pixels, and after the removal the picture was identical to the one before.

### D4. Printability on the mesh, not on B-rep faces

`check_printability` exports the part through `export_stl_with_settings`:
- `resolution: fine`, `units: mm`, binary;
- a new `translate_to_positive: false` option, which sets toggle 71 `swSTLDontTranslateToPositive` to true for the export, so mesh coordinates are model coordinates;
- a temporary file, deleted afterwards.

`utils/printability.py` (numpy, no COM) then works on the welded mesh. Let `d` be the unit build direction, `h = v · d` a vertex's height, and `h0` the lowest height.

- **Plate faces:** triangles with every vertex within 0.01 mm of `h0` are on the plate, and left out.
- **Down-facing:** `n · d < 0`. Its angle from horizontal is `acos(-n · d)` in degrees: 0 for a ceiling, 90 for a wall. Areas are summed in bands.
- **Regions:** down-facing triangles under `support_angle_deg` are grouped by shared edges.
- **Islands:**
  - A region whose boundary touches nothing lower is an island: no edge-adjacent outside triangle has a vertex below the shared edge.
  - So is a vertex that is a strict local minimum of `h` over its neighbours, above the plate.
- **Bridges:**
  - Take a region within 10° of horizontal. Its supported boundary edges are those whose adjacent outside triangle goes down. Chain them into runs.
  - Two or more runs make a bridge. Its `span_mm` is twice the largest distance from a triangle centroid to the nearest supported boundary point, measured in the plane perpendicular to `d`.
  - One run is an overhang, counted only in the bands.
- **Suction cups:**
  - Take a ceiling region (angle under 45°). Start a ray at its centroid, 0.01 mm toward the plate, and cast it four ways perpendicular to `d` and once toward the plate (`-d`).
  - All four sideways rays hit the mesh, and the plate-ward ray hits nothing: the cavity opens toward the plate, so it is a cup.
  - Its depth is the region's height above `h0`. Its area is the region's area projected along `d`.
  - The rays use Möller–Trumbore, vectorised over all triangles: a few rays per region.

**Alternative rejected:** B-rep faces through COM (`IFace2.Normal`, `GetBox`). Curved faces have no single normal, and a dish rack has hundreds of faces. The mesh gives uniform pieces and keeps the check out of COM.

The definitions are heuristics. The spec's scenarios (a flat block, a shelf, a cup) fix their behaviour, and the reply says what each list means.

### D5. Fillet and chamfer edges replaced through their definition

`feature_editing.replace_edges(adapter, name, edges)`:
1. Read the feature's type: `Fillet` → `ISimpleFilletFeatureData2`; `Chamfer` → `IChamferFeatureData2`; anything else is refused.
2. `GetDefinition`, then `AccessSelections(model, null component)`.
3. Put `Edges` as a `VT_ARRAY | VT_DISPATCH` of the new edges, then `ModifyDefinition`, then rebuild.
4. Read `GetEdgeCount()` (fillet) or the `Edges` length (chamfer) before and after.

A `ModifyDefinition` that returns False calls `ReleaseSelectionAccess`, and the feature is unchanged.

The edges come from one of two places, gathered before `AccessSelections`, which may clear the selection:
- `"selection"`: the selection manager's selected edges (`GetSelectedObject6`, type 1);
- `edge_rules`: `match_rules` on the active part, using the edge handles directly, without selecting them.

The tool checks the type and the arguments before SolidWorks is called, through `edit_feature`'s existing `check_changes`. Only `edges` / `edge_rules` may come with a fillet or chamfer, or `radius` on its own as today.

**Probe 2** also covers this step: whether `Edges` takes an array put through late binding, and whether a fillet that failed its rebuild accepts new edges.

### D6. The adapter interface

New adapter methods:
- `set_component_transform(component, origin_mm, rotation_rows, fixed)`
- `measure_clearance(component_a, component_b)`
- `check_printability(build_direction, support_angle_deg, min_bridge_mm)`: on the adapter, because it needs the export. The analysis itself is `utils/printability.py`.

Changed adapter inputs:
- `edit_feature` passes `edges` / `edge_rules` in its `changes` dict;
- `export_image` takes `section` in its payload;
- `insert_component` takes `fixed`.

`base.py`, `connection_pool.py` and `circuit_breaker.py` forward them. `mock_adapter.py` mirrors each:
- transforms are kept per component;
- clearance comes from canned component boxes;
- `export_image` records the section;
- printability runs the real `utils/printability.py` on a mock STL;
- edge replacement checks the feature type and counts.

### D7. Support levels

The three new tools start as `experimental` in `support_levels.py`, like every new tool, and move up after a live sign-off. `edit_feature`'s and `export_image`'s levels don't change.

## Risks / Trade-offs

- **Clearance speed:** box pruning may still measure many pairs on curved parts that sit close together. Mitigated by the stop rule; `pairs_checked` makes the cost visible. `limits.check` runs between measurements, as in the other loops.
- **Cylinder distances:** if probe 1 finds no face-level call right for cylinders, the reply loses its points (D2 fallback). The distance stays right.
- **A section left on:** the `finally` removes it. If removal fails, the reply carries a warning naming the section, and the next `export_image` with `section` removes it first.
- **Printability heuristics:** islands and cups are judged on a mesh, so a coarse mesh can hide a small island. The fine resolution and the spec's scenarios bound this. The reply's descriptions say these are checks, not a slicer.
- **STL coordinates:** without toggle 71, SolidWorks moves the mesh to positive space and every reported point is off by the part's minimum corner. D4 sets it for the export and puts it back.
- **Fillet edges:** a fillet made with faces or features as well as edges keeps those. Only its edges are replaced, and the reply says so.

## Probe results

Run on SOLIDWORKS 2026 SP4.1, 2026-11-13, scratch documents (`tests/scripts/probe_clearance.py`, `probe_section_fillet.py`).

- **Distances (probe 1):**
  - `ClosestDistance` minimum over the face pairs: pin in hole 0.249999 mm (33 pairs), tongue in slot 0.25 mm (66 pairs). The pin's cylinder against the hole's cylinder: 0.25 mm, between (10.61, 0, 1.81) and (10.38, 0, 1.90), points on the two surfaces.
  - `IEntity.GetDistance` (min): 0 mm on both, and 5.25 mm for the two cylinders, with points in the part's coordinates. Not usable.
  - `IMeasure.Calculate`: 0.25 mm on both.
  - `GetBox` on a face and on its assembly twin: the same, in the part's coordinates.
- **Rotation (probe 3):** after the rows for a quarter turn about Y, the read-back rotation was the rows asked, and the block's assembly box was x 90..100, y 0..6, z -20..0 mm, as `p . R + t` predicts.
- **Section (probe 2):** `CreateSectionView` and `RemoveSectionView` both returned True. 22.5% of sampled pixels changed with the section, 0% after it was removed.
- **Fillet and chamfer edges (probe 2):**
  - Putting `Edges` as a `VT_ARRAY | VT_DISPATCH` and `ModifyDefinition` worked on both.
  - A chamfer took the four edges given.
  - A fillet given its own top face's four edges kept two. One of them was the fillet's own tangent edge, and SolidWorks drops edges a fillet can't take. So the reply compares `edges_after` with the edges given, and warns when SolidWorks dropped some.
  - A fillet that failed after its L-shaped sketch was redrawn as a rectangle took a new edge, and the part rebuilt cleanly.

## Live results

Run on SOLIDWORKS 2026 SP4.1, 2026-11-13, scratch documents:
- `tests/live/test_live_sw_cellvis_gaps.py`: 13 passed on the first run. That covers every spec scenario:
  - the 137 mm stack, the quarter turn and the fixed base, all checked against `IComponent2.GetBox`;
  - the floating first insert and the mated component;
  - the block, shelf and pocket print checks;
  - the pin and tongue at 0.25 mm, and the 1 mm overlap;
  - the section picture;
  - the fillet repaired after a sketch edit, and the chamfer moved by a rule.
- The related live suites (regression, DishRack fixes, U-joint gaps, feature editing, `select_edges`, image options, STL settings, wall thickness, the `document` argument, beta tools): 107 passed, 2 skipped (they need a local assembly path).

## Open Questions

None left: the probes settled D1, D2, D3 and D5.
