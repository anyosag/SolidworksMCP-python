## Why

The Cellvis Dish Holder session builds a resin-printed dish rack (base, top, side bars, a snap latch, stacking assemblies) through this server. After its last build it ranked what still cost it the most time (message of 2026-11-12). Four items remain after the `dishrack-fixes` branch:

1. **Placing components.** Nothing sets a component's position or fixes it. The session wrote its own pywin32 script four times (`Select4`, `UnfixComponent`, `Transform2 = MathUtility.CreateTransform`, `FixComponent`, `ForceRebuild3`). It used that to put 8 dish stand-ins at exact heights, put a second rack 137 mm up for the stacking check, and move the base back to the origin.
2. **Clearances.** `check_interference` reports only overlaps. The 0.2–0.3 mm latch clearances, the 0.5 mm catch play and the 1.5 mm lid gap were checked only "by construction", plus a picture from outside. A snap inside its socket can't be seen without a section.
3. **Printing with fewer supports.** The user asked for parts that print in given orientations with few supports: base and top upright, bars lying flat. The session worked the overhangs out by hand.
4. **Fillets broken by an upstream edit.** After `edit_sketch` shortened the spine, `SpineEdgeFillet` failed. The session had to delete it, select edges again, add a new fillet and rename it.

The user agreed this scope on 2026-11-13: all four, not mates list/edit/delete. No GitHub issue: work on the fork `anyosag/SolidworksMCP-python`, branch `cellvis-gaps` from `dishrack-fixes`.

## What Changes

- **New tool `set_component_transform`:**
  - Inputs: `component`, `origin_mm`, a rotation (`rotation_deg` [rx, ry, rz] or `matrix` 3×3), and an optional `fixed`.
  - It moves the component's origin and axes in the assembly. A fixed component is floated for the move and fixed again unless `fixed` says otherwise.
  - It returns the transform read back, and whether it matches.
  - `insert_component` gains a `fixed` option.
- **New tool `measure_clearance`:**
  - Inputs: `component_a` and `component_b`.
  - It returns the minimum distance between them in mm, the two nearest points, and the names of the faces they lie on. Touching or overlapping components return 0, with a pointer to `check_interference`.
- **`export_image` section option:**
  - `section` is `{plane, offset_mm, reverse}`. It cuts the model on a plane for this picture only, so a snap in its socket can be seen. The section is removed afterwards.
- **New tool `check_printability`:**
  - Inputs: `build_direction` (the direction the part grows away from the build plate), and optional `support_angle_deg` (default 45) and `min_bridge_mm`.
  - It exports the active part to a temporary STL. It reports down-facing area in angle bands, islands (regions that start in mid-air), bridges (flat overhangs held at their ends, with their spans), and suction cups (cavities that open toward the build plate and trap resin).
  - Pure geometry on the mesh: no new COM beyond the existing STL export.
- **`edit_feature` takes a fillet's or chamfer's edges:**
  - `edges: "selection"` uses the current selection; `edge_rules` takes a `select_edges` query, `any_of` included.
  - Either one replaces the feature's edge set. The feature keeps its name, its radius or distances, and its place in the tree.
  - The reply reports the edge counts before and after.

## Capabilities

### New Capabilities
- `tools/component-placement`: setting a component's transform and fixed state, and `fixed` on insert.
- `tools/component-clearance`: the minimum distance between two components.
- `tools/image-section`: a section plane for one picture.
- `tools/printability`: the print-orientation check.

### Modified Capabilities
- `tools/edge-treatment`: an existing fillet's or chamfer's edges can be replaced.

## Impact

- **COM/adapter code (extra risk per CLAUDE.md):**
  - `adapters/solidworks/placement.py` (rotation, fixed), `io.py` (`insert_component`), new `clearance.py`, `pywin32_adapter.py` (`export_image` section), `feature_editing.py` (edge replacement).
  - `adapters/base.py`, `mock_adapter.py`, `connection_pool.py`, `circuit_breaker.py` for the new adapter methods.
  - New math and selection objects (`IMathUtility`, `IEntity`, `ISectionViewData`, `ISimpleFilletFeatureData2`, `IChamferFeatureData2`) must have their methods flagged before use (pitfalls #41 and #42).
- **Pure modules:** `utils/printability.py` (on `utils/stl_mesh.py`) and the rotation math in `placement.py`.
- **Tools:** `tools/modeling.py` (`set_component_transform`, `insert_component`, `measure_clearance`, `edit_feature`), `tools/export.py` (`export_image`), `tools/analysis.py` (`check_printability`). Also `support_levels.py`, `tool_hints.py`, the tool catalog, the progress files and the agent skill.
- **Docs:** pitfall entries for what the probes find, and the skill's assembly and printing workflows.
- **Tests:**
  - unit tests beside each module;
  - probe scripts `tests/scripts/probe_clearance.py` and `probe_section_fillet.py` (scratch documents);
  - a live test `tests/live/test_live_sw_cellvis_gaps.py`.
