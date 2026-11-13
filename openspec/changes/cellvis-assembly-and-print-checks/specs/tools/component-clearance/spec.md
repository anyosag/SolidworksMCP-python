## ADDED Requirements

### Requirement: The minimum distance between two components

`measure_clearance` SHALL return the minimum distance between the solid bodies of `component_a` and `component_b` in the active assembly, as `clearance_mm`. It SHALL also return `point_a_mm` and `point_b_mm` (the nearest points, in assembly coordinates), `face_a` and `face_b` (a description of the face each point lies on: its kind and its box), and `pairs_checked` (how many face pairs were measured). It SHALL be accurate to 1e-3 mm for planar and cylindrical faces.

A cylinder SHALL be measured to its surface, not its axis.

#### Scenario: A latch tongue in its slot
- **WHEN** a 4.0 mm tongue sits centred in a 4.5 mm slot and an agent calls `measure_clearance` on the two components
- **THEN** `clearance_mm` is 0.25 within 1e-3, and the two points lie on facing walls 0.25 mm apart

#### Scenario: A pin in a hole
- **WHEN** a Ø9.5 mm pin sits concentric in a Ø10 mm hole
- **THEN** `clearance_mm` is 0.25 within 1e-3, not 0 (the axes' distance)

### Requirement: Touching and overlapping components are not a clearance

When the two components touch or overlap, `clearance_mm` SHALL be 0 and `touching` SHALL be true, and the reply SHALL include a `warning` saying to use `check_interference` for the overlap's volume.

#### Scenario: A deliberate 1 mm overlap
- **WHEN** two blocks overlap by 1 mm
- **THEN** the reply has `clearance_mm: 0`, `touching: true` and the warning

### Requirement: Bad requests are named

An unknown component SHALL fail with `error_type: not_found`, listing the assembly's components. The same component twice, or an active document that isn't an assembly, SHALL fail with `error_type: invalid_input`. A component with no solid body (a sketch-only part, or a suppressed component) SHALL fail with `error_type: invalid_input` and say which one.

#### Scenario: A suppressed component
- **WHEN** `component_b` is suppressed
- **THEN** the call fails with `error_type: invalid_input`, and the message names `component_b`
