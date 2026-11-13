## 1. Probes (SolidWorks, scratch documents, each with the user's OK)

- [x] 1.1 `tests/scripts/probe_clearance.py`.
  - Build a Ø9.5 pin concentric in a Ø10 hole, and a 4.0 tongue in a 4.5 slot.
  - Measure each with `IEntity.GetDistance` (min), `ClosestDistance` and `IMeasure`.
  - Check that `GetBodies3` face boxes on an offset component come in the part's coordinates.
  - Record the results in design.md under "Probe results", and settle D2's measuring call.
- [x] 1.2 `tests/scripts/probe_section_fillet.py`.
  - Section: create a section view on Front Plane with an offset; take a picture; find the call that removes it (`CreateSectionView(None)`, `RunCommand`). Prove removal with a second picture.
  - Fillet: put `Edges` on a fillet and on a chamfer through late binding, including a fillet that failed its rebuild after a sketch edit.
  - Record the results; settle D3's removal call and D5.
- [x] 1.3 Rotation convention.
  - Put `Transform2` with the quarter turn about Y from the spec.
  - Read where the component's X axis points, and settle D1's row convention.

## 2. Component placement

- [x] 2.1 `adapters/solidworks/placement.py`:
  - `place(...)` with `rotation_rows` and `fixed` (D1), and `rotation_rows_from_deg`;
  - an orthonormal check for matrices;
  - `insert_component` moves to `place`;
  - tests in `test_placement.py`.
- [ ] 2.2 Adapter `set_component_transform`:
  - in `adapters/solidworks/io.py` (find the component, `place`, a warning when held by mates), and `insert_component(..., fixed)`;
  - `base.py`, `connection_pool.py` and `circuit_breaker.py` forward them;
  - tests beside each.
- [ ] 2.3 `mock_adapter.py`: a transform and fixed state per component, `set_component_transform`, and `insert_component(fixed)`; tests in `test_mock_adapter*.py`.
- [ ] 2.4 Tools in `tools/modeling.py`:
  - `set_component_transform` (`SetComponentTransformInput`: `rotation_deg` and `matrix` exclusive, matrix checked);
  - `fixed` on `InsertComponentInput`;
  - descriptions per the standard;
  - `support_levels.py` (experimental) and `tool_hints.py`;
  - tests in `tests/solidworks_mcp/tools/`.

## 3. Clearance

- [x] 3.1 `adapters/solidworks/clearance.py`:
  - pure box lower bounds and the pair order, with the stop rule;
  - the COM walk of bodies and faces, with the measuring call from probe 1;
  - `limits.check` between measurements;
  - tests in `test_clearance.py` with fake faces.
- [x] 3.2 Adapter `measure_clearance` (`pywin32_adapter` / `io.py`), forwarded by `base.py`, `connection_pool.py` and `circuit_breaker.py`; the errors for unknown, same, suppressed and bodiless components; tests.
- [x] 3.3 `mock_adapter.py` `measure_clearance` from canned component boxes and the stored transforms; tests.
- [x] 3.4 Tool `measure_clearance` in `tools/modeling.py`:
  - the `touching` warning;
  - support level and hints;
  - tests.

## 4. Section in pictures

- [x] 4.1 `pywin32_adapter.export_image`: `section` (find the plane, `ISectionViewData`, create, and remove in the `finally`); an unknown plane fails before the picture; tests in `test_pywin32_adapter_image_options.py`.
- [x] 4.2 `mock_adapter.py` `export_image` records and reports `section`, and refuses an unknown plane; tests.
- [x] 4.3 `ExportImageInput.section` (`plane`, `offset_mm`, `reverse`); description; tests.

## 5. Printability

- [x] 5.1 `utils/printability.py`:
  - plate faces, angle bands, regions, islands, bridges (supported runs, span) and suction cups (vectorised rays);
  - tests in `tests/solidworks_mcp/utils/test_printability.py` with meshes built in the test: a block, a shelf, a bottom-open pocket, an island, a bridge.
- [x] 5.2 `stl_settings`: a `translate_to_positive` setting (toggle 71), set for one export and put back; tests in `test_stl_settings.py`.
- [ ] 5.3 Adapter `check_printability`:
  - in `pywin32_adapter.py`: a part only; export to a temporary STL with fine resolution, mm and no translation; analyse; delete the file;
  - forwarded by `base.py`, `connection_pool.py` and `circuit_breaker.py`;
  - tests.
- [ ] 5.4 `mock_adapter.py` `check_printability`: the real analysis on the mock's STL; tests.
- [ ] 5.5 Tool `check_printability` in `tools/analysis.py`:
  - direction names or vector;
  - `support_angle_deg`, `min_bridge_mm`;
  - support level and hints;
  - tests.

## 6. Fillet and chamfer edges

- [ ] 6.1 `feature_editing.py`:
  - `check_changes` accepts `edges` / `edge_rules` for `Fillet` and `Chamfer`;
  - `replace_edges` (D5: gather edges before `AccessSelections`, put `Edges`, `ModifyDefinition`, counts before and after, release on refusal);
  - tests in `test_feature_editing.py`.
- [ ] 6.2 Adapter `edit_feature` wiring (`features.py`): the selected edges or `match_rules` handles; `measured_change`; tests.
- [ ] 6.3 `mock_adapter.py` `edit_feature` with `edges` / `edge_rules`: type check and counts; tests.
- [ ] 6.4 `EditFeatureInput`:
  - `edges` (`"selection"`) and `edge_rules` (a `select_edges` query, validated by `validate_edge_query`), exclusive;
  - description;
  - tests.

## 7. Docs and checks

- [ ] 7.1 `docs/agents/com-api-pitfalls.md`: what the probes found (distance calls on cylinders, section removal, fillet `Edges`, STL translation); the skill's assembly and printing workflows (`src/solidworks_mcp/skills/solidworks-mcp/`).
- [ ] 7.2 Regenerate the tool catalog (`src/utils/generate_tool_catalog.py`) and the progress files (`python -m solidworks_mcp.progress.generate`).
- [ ] 7.3 `ruff check` / `ruff format --check`, and the full mock suite with the coverage gate.

## 8. Live

- [ ] 8.1 `tests/live/test_live_sw_cellvis_gaps.py`, one test per spec scenario, on scratch documents: stack 137 mm up, quarter turn, move the fixed base, mated component, floating first insert, tongue and pin clearances, overlap, section picture, block, shelf and cup printability, fillet repair, chamfer by rule.
- [ ] 8.2 Run it with the user's OK; fix what it finds; record measurements in design.md.
