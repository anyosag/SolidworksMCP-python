## ADDED Requirements

### Requirement: A component's origin and axes can be set

`set_component_transform` SHALL place a component of the active assembly so that its own origin is at `origin_mm`, and its axes are turned by the rotation given, in assembly coordinates. It SHALL read the transform back and return it as `transform` (`origin_mm`, and `rotation` as three rows, each a component axis in assembly coordinates). It SHALL return `placed`: whether the transform read back matches within 1e-4 mm and 1e-6.

The rotation SHALL be given one of three ways:
- `rotation_deg: [rx, ry, rz]`: turns about the assembly's X, then Y, then Z axis, in degrees, by the right-hand rule;
- `matrix`: three rows of three numbers, the component's X, Y and Z axes in assembly coordinates, orthonormal within 1e-6;
- neither: the component's current rotation is kept.

Giving both, or a `matrix` that is not orthonormal, SHALL be refused as invalid input before SolidWorks is called.

#### Scenario: A rack stacked 137 mm up
- **WHEN** an assembly holds two racks and an agent calls `set_component_transform` with `component: "DishRack_Assembly-2"` and `origin_mm: [0, 137, 0]`
- **THEN** the reply has `placed: true` and `transform.origin_mm` is [0, 137, 0], and the rotation is unchanged

#### Scenario: A stand-in turned a quarter turn about Y
- **WHEN** an agent gives `origin_mm: [10, 20, 30]` and `rotation_deg: [0, 90, 0]`
- **THEN** `transform.rotation`'s first row (the component's X axis) is [0, 0, -1] in assembly coordinates, and its origin is at [10, 20, 30]

#### Scenario: Both rotations given
- **WHEN** an agent gives `rotation_deg` and `matrix`
- **THEN** the call fails with `error_type: invalid_input`, and nothing moves

### Requirement: A fixed component can be moved, and fixed or floated

A fixed component SHALL be floated for the move and fixed again afterwards. With `fixed: true` or `fixed: false`, the component SHALL end in that state whatever it was before. The reply SHALL give `fixed` as read back.

#### Scenario: Moving the base back to the origin
- **WHEN** the base is the assembly's first, fixed component, off the origin, and an agent calls `set_component_transform` with `origin_mm: [0, 0, 0]`
- **THEN** the base's origin is at the assembly origin, and it is still fixed

#### Scenario: Fixing a stand-in where it was put
- **WHEN** an agent places a floating stand-in with `fixed: true`
- **THEN** the reply has `fixed: true`, and a later mate doesn't move it

### Requirement: A component that isn't there is named

An unknown `component` SHALL fail with `error_type: not_found`, listing the assembly's components. A part or drawing as the active document SHALL fail with `error_type: invalid_input`. A component SolidWorks won't move, such as one held by mates, SHALL be reported as `placed: false` with the transform read back, and a warning that names the mates as the likely reason.

#### Scenario: A mated component
- **WHEN** a component is held by a coincident mate and an agent moves it off that face
- **THEN** the reply has `placed: false`, `transform` where SolidWorks kept it, and a warning that mentions its mates

### Requirement: insert_component can fix the component

`insert_component` SHALL take an optional `fixed`. With `fixed: true` the inserted component SHALL be fixed; with `false` it SHALL float, including when it is the assembly's first component, which SolidWorks fixes by itself. The reply's `placement` SHALL include `fixed` as read back.

#### Scenario: A floating first component
- **WHEN** an agent inserts the first part of a new assembly with `fixed: false`
- **THEN** the reply has `placement.fixed: false`
