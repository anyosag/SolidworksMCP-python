# Analysis Tools

Extract engineering properties from models: mass, volume, centre of mass, moments of inertia, interference between solids, geometry curvature and thickness, and material properties. Essential for design validation.

> **Prerequisite:** An active model (part or assembly) with solid geometry.

**Total tools in this category: 8**

---

### `calculate_mass_properties`

Measure the active part or assembly's mass properties: volume, surface area, mass, centre of mass and moments of inertia.

**Prerequisite:** Active model with solid geometry

**Sample call:**

```json
{}
```

---

### `get_mass_properties`

Measure the active part or assembly's mass properties: volume, surface area, mass, centre of mass and moments of inertia.

**Prerequisite:** Active model with solid geometry

**Sample call:**

```json
{}
```

---

### `check_interference`

Find where the components of the active assembly overlap (Tools > Interference Detection).

**Prerequisite:** Active assembly

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `assembly_path` | `str?` | — | `None` | Assembly path alias |
| `include_hidden` | `bool` | — | `False` | Check hidden components too; by default they are left out, as in SolidWorks' own Interference Detection |
| `components` | `List[str]` | ✅ | `` | List of component names to check for interference |

**Sample call:**

```json
{
  "components": []
}
```

---

### `analyze_geometry`

Run a geometry analysis on the active model, such as curvature, draft or wall thickness.

**Prerequisite:** Active model with geometry

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `analysis_type` | `str` | ✅ | `` | Type of analysis (curvature, draft, thickness, etc.) |
| `parameters` | `Dict[str, Any]?` | — | `None` | Analysis-specific parameters |

**Sample call:**

```json
{
  "analysis_type": "curvature"
}
```

---

### `check_wall_thickness`

Measure the active part's thinnest walls before 3D printing it.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `min_wall_mm` | `float` | — | `0.8` | The thinnest wall the printer can make, mm (0.8 is two 0.4 mm nozzle lines); thinner spots are listed |
| `max_rays` | `int` | — | `5000` | The most points to measure; more finds thin spots on big parts, slower (default 5000) |
| `exclude_boxes_mm` | `List[Annotated[List[float], Field(min_length=6, max_length=6)]]?` | — | `None` | Regions meant to be thin, such as a snap-fit flexure: each box is [x1, y1, z1, x2, y2, z2], two opposite corners in the part's coordinates, mm. Points inside a box (edges included) don't count against ok, min_thickness_mm or thin_spots; data.excluded reports them |

**Sample call:**

```json
{}
```

---

### `check_printability`

Check the active part for 3D printing (resin or FDM) in one orientation: overhangs, islands, bridges and suction cups.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `build_direction` | `str | List[float]` | ✅ | `` | The direction the part grows away from the build plate: 'x', 'y', 'z', '-x', '-y', '-z' or [x, y, z]. A part printed upright on its base, with Y up in the model, is 'y' |
| `support_angle_deg` | `float` | — | `45.0` | Surfaces facing the plate at less than this many degrees from horizontal need supports (default 45) |
| `min_bridge_mm` | `float` | — | `5.0` | Only flat overhangs held at both ends longer than this are listed, mm |

**Sample call:**

```json
{
  "build_direction": "example"
}
```

---

### `get_material_properties`

Report the physical properties of the active part's material: density, modulus, Poisson's ratio, strength.

**Prerequisite:** Active part with assigned material

**Sample call:**

```json
{}
```

---

### `verify_model`

Check the active part or assembly against what you meant to build, one pass/fail check per expected value.

**Prerequisite:** SolidWorks running

**Sample call:**

```json
{}
```

---
