## ADDED Requirements

### Requirement: A part is checked for printing in one orientation

`check_printability` SHALL check the active part for printing with `build_direction`: `x`, `y`, `z`, `-x`, `-y`, `-z` or a vector, the direction the part grows away from the build plate. It SHALL check the part's own geometry, written to a temporary STL at a fine mesh and deleted afterwards, and SHALL leave the user's STL options as they were.

The reply's `data` SHALL hold:
- `down_facing`: the area (mm²) of surfaces facing the build plate, in bands of their angle from the plate: 0–15°, 15–30°, 30–45°, 45–60°, 60–90° from horizontal. `needs_support_mm2` is the area under `support_angle_deg` (default 45).
- `islands`: regions that start in mid-air, the lowest point of an overhang with nothing below it at any height. Each has its lowest point in mm and its area.
- `bridges`: flat overhangs (within 10° of horizontal) held at both ends. Each has `span_mm` (the shortest distance across it), its centre and its area. Only spans over `min_bridge_mm` (default 5) are listed.
- `suction_cups`: cavities that open toward the build plate and are closed on every other side. Each has its opening's centre, its area and its depth along the build direction.
- `ok`: true when there are no islands, no suction cups, no listed bridges and no area under `support_angle_deg`, excluding the face on the build plate.

The first layer, the lowest faces touching the plate, SHALL NOT count as down-facing.

#### Scenario: A block printed flat
- **WHEN** a 40 × 20 × 10 mm block is checked with `build_direction: "z"`
- **THEN** `ok` is true, `down_facing.needs_support_mm2` is 0, and there are no islands, bridges or cups

#### Scenario: An overhanging shelf
- **WHEN** a part has a 10 × 20 mm horizontal shelf sticking out 10 mm, 8 mm above the plate
- **THEN** the shelf's 200 mm² underside is in the 0–15° band, `needs_support_mm2` is at least 200, and `ok` is false

#### Scenario: A cup that opens toward the plate
- **WHEN** a 30 mm box with a 20 × 20 × 15 mm pocket open on its bottom face is checked with `build_direction: "z"`
- **THEN** `suction_cups` lists one cavity, depth 15 mm, opening area 400 mm²; checked with `build_direction: "-z"`, it lists none

### Requirement: The check needs a part

An assembly, a drawing or no open document SHALL fail with `error_type: invalid_input`. A zero vector or an unknown direction name SHALL be refused as invalid input.

#### Scenario: An assembly
- **WHEN** the active document is an assembly
- **THEN** the call fails with `error_type: invalid_input`, saying to check each part
