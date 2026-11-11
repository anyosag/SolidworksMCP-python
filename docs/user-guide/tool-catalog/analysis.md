# Analysis Tools

Extract engineering properties from models: mass, volume, centre of mass, moments of inertia, interference between solids, geometry curvature and thickness, and material properties. Essential for design validation.

> **Prerequisite:** An active model (part or assembly) with solid geometry.

**Total tools in this category: 7**

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

**Sample call:**

```json
{}
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
