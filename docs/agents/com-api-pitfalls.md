# COM API Pitfalls for LLM Agents

This page documents hard-won lessons from debugging the SolidWorks COM bridge.
If you are an AI coding assistant (Claude, GPT-4, Gemini, Copilot, etc.) working on this codebase,
**read this page before touching any COM-related code**.
Every entry below caused a real runtime failure that required hours to diagnose.

!!! tip "For LLM agents"
    The patterns here are not obvious from the SolidWorks API docs alone.
    They are the delta between "what the documentation says" and "what actually works"
    under pywin32 late-binding on SW 2025/2026.

!!! note "Using the server, not changing it?"
    This page is for changing the COM code. For how an agent should *use* the
    tools (build order, units, selection, known limits), see the
    [Agent Skill](agent-skill.md).

---

## 1. `SelectByID2` — `Callout` must be `VT_DISPATCH` null, not `None`

**Symptom:** `(-2147352571, 'Type mismatch.', None, 8)` when calling `SelectByID2`.

**Root cause:** The `Callout` parameter (8th argument, type `VT_DISPATCH`) expects a COM
null pointer, not a Python `None`. Python `None` marshals as `VT_NULL` which SolidWorks
rejects with `DISP_E_TYPEMISMATCH`.

**Fix:**

```python
import pythoncom
import win32com.client as _win32com

null_callout = _win32com.VARIANT(pythoncom.VT_DISPATCH, None)
model.Extension.SelectByID2(
    "", "EDGE", x, y, z,
    append, mark,
    null_callout,   # <- NOT plain None
    0,
)
```

**Applies to:** Every call to `SelectByID2` or `SelectByID` that doesn't need a real callout object.
The same issue occurs for `FACE`, `EDGE`, `VERTEX`, and other entity types.

---

## 2. `InsertFeatureChamfer` lives on `IFeatureManager`, not `IModelDocExtension`

**Symptom:** `<unknown>.InsertFeatureChamfer` error when calling through `model.Extension`.

**Root cause:** `InsertFeatureChamfer` (DISPID 83) is a method of `IFeatureManager`, not
`IModelDocExtension`. Routing it through `model.Extension` causes `DISP_E_MEMBERNOTFOUND`.

**Fix:**

```python
import math

fm = model.FeatureManager          # IFeatureManager (property access, no parens)
feature = fm.InsertFeatureChamfer(
    1,                             # Options
    1,                             # ChamferType = swChamferEqualDistance
    distance_m,                    # Width in metres
    math.pi / 4,                   # Angle (45 degrees)
    0.0,                           # OtherDist (unused for equal-distance)
    0.0, 0.0, 0.0,                 # VertexChamDist1, 2, 3 (unused)
)
```

**Applies to:** Any chamfer feature creation. Do not use `model.Extension.InsertFeatureChamfer`.

---

## 3. `ForceRebuild3` must run before coordinate-based edge/face selection

**Symptom:** `SelectByID2("", "EDGE", x, y, z, ...)` returns `False` even when the coordinate
is geometrically on an edge.

**Root cause:** After creating a feature (revolve, cut, extrude), the new edges are not
tessellated until the model is explicitly rebuilt. `SelectByID2` uses the tessellated mesh to
find nearby entities; without it, the edge does not exist in the selection index.

**Fix:** Call `ForceRebuild3(True)` before the first coordinate-based selection in any
feature operation:

```python
model.ForceRebuild3(True)   # True = top-level only (faster); False = deep rebuild
model.Extension.SelectByID2("", "EDGE", x, y, z, False, 0, null_callout, 0)
```

**Only needed once** per feature-creation sequence, before the first `SelectByID2` call.

---

## 4. `GetTessellation` is on `IFace2`, not on `IEdge`

**Symptom:** `<source>.GetTessellation` error when iterating `body.GetEdges()` and calling
`edge.GetTessellation(tol)`.

**Root cause:** `GetTessellation` is a method of `IFace2` (face objects), not `IEdge`.
Edge objects do not have a tessellation method accessible via late binding.

**What to use instead for edge sampling:** `IEdge.GetCurveParams2` (property, no parens) returns
`[t0, t1, ...]`; then use the `ICurve` returned by `IEdge.GetCurve` and call
`curve.Evaluate2(t, 0)` to sample points.

```python
params = edge.GetCurveParams2    # property — no ()
curve  = edge.GetCurve           # property — no ()
t0, t1 = float(params[0]), float(params[1])
pt = curve.Evaluate2((t0 + t1) / 2, 0)   # midpoint
```

But prefer `SelectByID2` with coordinates over body traversal — it is faster and more reliable.

---

## 5. Zero-arg COM methods accessed without `()` in late binding

**Symptom:** `TypeError: 'str' object is not callable` or `TypeError: 'tuple' object is not callable`.

**Root cause:** Under pywin32 late binding, zero-argument COM methods are returned as their
result value (property-style), not as callable objects. Calling `()` on the result tries to
invoke the returned value (a string, tuple, etc.) as a function.

**Examples:**

```python
# WRONG
title = model.GetTitle()     # TypeError: 'str' is not callable
params = edge.GetCurveParams2()  # TypeError: 'tuple' is not callable

# CORRECT
title = model.GetTitle       # returns the string directly
params = edge.GetCurveParams2    # returns the tuple directly
```

**Rule:** Any SW method with no parameters must be accessed **without** `()`.
The `sw_type_info.flag_methods` system handles which names are treated as methods vs properties.
Check `gen_py` (`IEdge`, `IModelDoc2`, etc.) to see whether a name is a `def` (method) or
in `_prop_map_get_` (property).

---

## 6. `FeatureChamfer(Width, Angle, Flip)` returns `int`, not `IFeature`

**Symptom:** Checking `if not feature:` fails even on success; `feature.Name` crashes.

**Root cause:** `IModelDoc2.FeatureChamfer(Width, Angle, Flip)` (DISPID 65583) returns
`VT_I4` (an integer): `1` on success, `0` on failure. It does **not** return an `IFeature`.
Code that treats the return value as a COM object will fail.

**Fix:** Use `IFeatureManager.InsertFeatureChamfer` (see pitfall #2) which returns a proper
`IFeature`. If you must use the `IModelDoc2` variant as a fallback, check the int:

```python
result_int = model.FeatureChamfer(width_m, math.pi / 4, False)
if not result_int:
    raise Exception("FeatureChamfer returned 0 (failure)")
# result_int is now 1 (truthy), not an IFeature
```

---

## 7. `IModelDoc2.FeatureFillet3` on SW 2025+ returns `int`, not `IFeature`

**Symptom:** `feature.Name` raises `AttributeError: int object has no attribute Name`.

**Root cause:** Starting with SW 2025 (major version ≥ 33), `IModelDoc2.FeatureFillet3`
returns `VT_I4` (1 = success, 0 = failure), not an `IFeature` dispatch object.
The older `IFeatureManager.FeatureFillet3` still returns `IFeature` on older builds.

**Fix:** Branch on SW major version:

```python
rev = adapter.swApp.RevisionNumber
major = int(str(rev).split(".")[0])

if major >= 33:
    result_code = model.FeatureFillet3(radius_m, True, 0, False, 0, 0, None, False, False)
    if not result_code:
        raise Exception("FeatureFillet3 returned 0")
    # Feature exists but IFeature reference is not available; name defaults to "Fillet"
else:
    feature = model.FeatureManager.FeatureFillet3(radius_m, 0, 0, 0, 0, ...)
    if not feature:
        raise Exception("FeatureFillet3 returned None")
    name = feature.Name
```

---

## 8. The `<unknown>.<Method>` error pattern

**Symptom:** Error message like `<unknown>.InsertFeatureChamfer` or `GetEdges.GetTessellation`.

**Root cause:** This is pywin32's error format when `IDispatch.GetIdsOfNames` returns
`DISP_E_MEMBERNOTFOUND` for a method name. It means you are calling a method on the **wrong COM
interface** — the COM object does not know that method name.

**The format:** `<ProgId>.<MethodName>` where `<ProgId>` is how pywin32 identified the object
(`<unknown>` if it has no registered ProgId, or a method name if the object was returned from a call).

**How to diagnose:**
1. Check the gen_py file for which class owns the method (search for `def MethodName`).
2. Confirm the class name printed near the `def` is the interface you are calling through.
3. If they differ, navigate through the correct property chain to reach the right interface.

---

## 9. `InsertRefPlane` for face sketches is more reliable than `SelectByID2 FACE`

**Symptom:** Sketch placed via `SelectByID2 FACE` fails after a parametric cut operation
because the face topology name has changed and the new face isn't found.

**Fix:** Create an offset reference plane from a named plane (e.g. Top Plane) and open a
sketch on that instead:

```python
top_plane = model.FeatureByName("Top Plane") or model.FeatureByName("Planta")
top_plane.Select2(False, 0)
# swRefPlaneReferenceConstraints_Distance = 8
offset_feat = model.FeatureManager.InsertRefPlane(8, offset_m, 0, 0.0, 0, 0.0)
offset_feat.Select2(False, 0)
sketch = model.SketchManager.InsertSketch(True)
```

See [`build_yoke_female_artifact.py`](../getting-started/tutorial-parts/build_yoke_female_artifact.py)
for a full working implementation.

---

## 10. `ThroughAll` vs `ThroughAllBoth` for mid-plane sketches

**Symptom:** A cut extruded from a mid-plane sketch (e.g. Top plane at Y=0) only cuts
in one direction, leaving half the material untouched.

**Root cause:** `swEndCondThroughAll` (value `1`) cuts only in Direction 1 from the sketch
plane. When the sketch is at Y=0 and the body extends from Y=-10 to Y=+10, Direction 1 goes
to Y=+10 but Direction 2 is not cut.

**Fix:** Pass `end_condition="ThroughAllBoth"`, or `"ThroughAll"` with
`both_directions=True`:

```python
await adapter.create_cut_extrude(
    ExtrusionParameters(end_condition="ThroughAllBoth")
)
```

The adapter builds this as a double-ended cut (`Sd=False`, `T1=T2=swEndCondThroughAll`).
A single-ended `FeatureCut4` with `T1=swEndCondThroughAllBoth` (value `9`) returns no
feature on SolidWorks 2026 for a valid closed sketch, so the adapter only tries it as a
fallback.

---

## 11. `GetType()` resolves as a property, not a method, on a freshly-fetched `ActiveDoc`

**Symptom:** `TypeError: 'int' object is not callable` when calling `document.GetType()` —
but the *identical* call on a document just returned by `OpenDoc6`/`NewDocument` works fine.
If this exception is caught by a broad `except Exception: return default` (e.g. this
codebase's `_attempt` helper), the failure is silent: the caller just sees `doc_type == 0`
and takes the wrong branch (e.g. treating an Assembly as unrecognized).

**Root cause:** Late-bound COM dispatch resolves an unknown member name speculatively —
sometimes as a callable method wrapper, sometimes by eagerly invoking it and returning the
*value* (property semantics). Which one you get depends on whether the specific dispatch
object has been flagged for its real interface via `sw_type_info.flag_doc`/`flag_methods`
(`_FlagAsMethod`). A document object returned directly by `OpenDoc6` in this codebase's
adapter is flagged immediately after open. A document re-fetched via `swApp.ActiveDoc` in a
later call (e.g. a resync-before-traversal step) is a **new, unflagged** dispatch wrapping
the same underlying document — `GetType` on it resolves as a property, and calling it with
`()` tries to call the returned `int`.

**Fix:** Never call a zero-arg accessor on a document/feature/component with bare
parentheses unless you know it has just been flagged. Route through the existing
`_get_attr_or_call(obj, "MethodName")` helper, which handles both property and method
resolution:

```python
doc_type = adapter._attempt(
    lambda: int(adapter._get_attr_or_call(document, "GetType") or 0), default=0
)
```

Found and fixed 2026-08-11 while verifying assembly-aware `list_features`
(`_FeatureSelectionService.list_features` in `pywin32_adapter.py`) against a live
SolidWorks session — see `openspec/changes/archive/2026-10-30-assembly-aware-list-features/`.

## 12. `IComponent2.GetModelDoc2` raises "Member not found" unless `IComponent2` is flagged first

**Symptom:** `pywintypes.com_error: (-2147352573, 'Member not found.', None, None)` when
calling `component.GetModelDoc2()` on an `IComponent2` object returned by
`IAssemblyDoc.GetComponents`, even though `getattr(component, "GetModelDoc2", None)`
returns something that looks callable.

**Root cause:** Same late-binding ambiguity as #11 and #5, but manifesting as a COM error
instead of a Python `TypeError`: dynamic dispatch returns a speculative callable wrapper for
an attribute name it hasn't resolved a real DISPID for yet, and that wrapper only fails once
actually invoked. `IComponent2` is never flagged anywhere else in the traversal — components
come from `GetComponents`, not from `flag_doc` (which only knows about document-level
interfaces: `IPartDoc`/`IAssemblyDoc`/`IDrawingDoc`).

**Fix:** Flag the component for `IComponent2` before calling any of its methods:

```python
sw_type_info.flag_methods(component, "IComponent2")
resolved_doc = adapter._get_attr_or_call(component, "GetModelDoc2")
```

Found and fixed 2026-08-11 alongside #11, in the same live-verification pass. Before this
fix, every component in a real assembly resolved as `UnresolvedComponent` — the traversal
logic itself was correct (confirmed by unit tests against mock COM fakes), but nothing had
ever exercised it against a real, unflagged `IComponent2` dispatch until then. A reminder
that mock-adapter tests validate the *shape* of a fix, not COM binding behavior itself.

---

## 13. `ToolsCheckInterference2` cannot report a result under late binding

**Symptom:** the call either raises, or succeeds while telling you nothing — both
out-parameters come back `None` on an assembly that visibly interferes.

**Root cause:** `IAssemblyDoc::ToolsCheckInterference2` is declared `Sub` — it returns
nothing — and reports through two `ByRef` out-parameters, `PComp` and `PFace`. Under
pywin32 late binding there is no call form that populates them. Every variant, measured
against a two-component assembly built from the same part twice:

| Call form | Result |
|---|---|
| `pythoncom.Missing` for both out-params | `TypeError: Objects of type 'PyOleMissing' can not be converted to a COM VARIANT` |
| three arguments, out-params omitted | `com_error: (-2147352561, 'Parameter not optional.', None, None)` |
| plain Python `None` for both | `com_error: (-2147352571, 'Type mismatch.', None, 4)` |
| `VARIANT(VT_BYREF \| VT_ARRAY \| VT_DISPATCH, None)` | `com_error: (-2147352571, 'Type mismatch.', None, 4)` |
| component array as `LpComponents` | `com_error: (-2147417851, 'The server threw an exception.', None, None)` |
| `VARIANT(VT_BYREF \| VT_VARIANT, None)` for both | **accepted** — returns `None`, and `PComp.value` / `PFace.value` are both `None`, for an interfering *and* a non-interfering assembly alike |

The last row is the dangerous one: nothing raises, so it reads as a clean result.

**The mistake this invites:** treating the return value as a count.

```python
# WRONG — ToolsCheckInterference2 is a Sub; there is no return value to read.
raw = model.ToolsCheckInterference2(0, None, coincident, missing, missing)
count = int(raw[0]) if raw else 0     # -> 0, i.e. "no interference", always
```

An inspection routine that always answers "nothing found" is worse than one that
refuses, because a caller has no way to tell the two apart.

**Fix:** use the interference-detection manager instead. `GetInterferenceCount` is an
ordinary return value, so `0` is a measurement rather than a swallowed failure:

```python
manager = sw_type_info.flagged(
    assembly.InterferenceDetectionManager, "IInterferenceDetectionMgr"
)
manager.TreatCoincidenceAsInterference = False
manager.IncludeMultibodyPartInterferences = True
try:
    count = int(manager.GetInterferenceCount() or 0)
    interferences = manager.GetInterferences() if count else None
finally:
    manager.Done()      # leaves the assembly out of interference-display mode
```

Measured on the same two assemblies: two coincident copies of a 32000 mm³ block gave
`GetInterferenceCount() -> 1` and `GetInterferences()` a 1-tuple; moving one copy 100 mm
away gave `0` and `None`.

Call `Done()` from a `finally` — a failed read otherwise leaves the assembly in
interference-display mode.

Found 2026-08-14 while implementing `check_interference` against a live SolidWorks 2025
session (gen_py wrapper `83A33D31-…x0x33x0`).

---

## 14. `IInterference.Components` is a property, not a method

**Symptom:** `AttributeError: GetInterferences.GetComponents`, or
`com_error: (-2147352562, 'Invalid number of parameters.', None, None)` from
`IGetComponents`.

**Root cause:** `IInterference` exposes its components as the **property**
`Components`. There is no `GetComponents()` on the interface at all, and
`IGetComponents(n)` — which the type library declares as taking a component count —
rejects that argument. Same late-binding member ambiguity as #5, reached from the
opposite direction.

**Fix:**

```python
item = sw_type_info.flagged(raw_interference, "IInterference")

volume_m3 = item.Volume                 # property, cubic metres
component_count = item.GetComponentCount()   # method, takes ()
components = item.Components            # property — no (), and not GetComponents()

for component in components:
    name = sw_type_info.flagged(component, "IComponent2").Name2
```

`Volume` is worth reading: it is the overlap volume in cubic metres and makes an
independent check possible. Two exactly coincident copies of a 32000 mm³ part reported
`3.2000000000000005e-05` m³ — the whole part volume, as it must be.

Found 2026-08-14 alongside #13.

---

## 15. Default template slots are 8, 9 and 10 — slots 0–3 are empty

**Symptom:** `NewDocument` fails, or a new-document helper reports "failed to create"
with no further detail.

**Root cause:** `ISldWorks::GetUserPreferenceStringValue` returns an empty string for the
low slot numbers on SW 2025. Code that reads slot `0` or `1` for a template path passes
`""` straight into `NewDocument`, and every operation downstream of it fails at the first
step. Measured on SW 2025:

| Slot | Value |
|---|---|
| 0, 1, 2, 3 | `''` (empty) |
| 6 | `…\SOLIDWORKS 2025\templates\` (directory) |
| 7 | `…\lang\english\sheetformat` (directory) |
| **8** | `…\templates\Part.prtdot` |
| **9** | `…\templates\Assembly.asmdot` |
| **10** | `…\templates\Drawing.drwdot` |

**Fix:** probe the document-specific slot first and fall back, and check the extension
and that the file exists rather than trusting the first non-empty string:

```python
for index in (10, 1, 0, 2, 3):        # drawing; use (8, …) part, (9, …) assembly
    template = app.GetUserPreferenceStringValue(index)
    if template and template.lower().endswith(".drwdot") and os.path.exists(template):
        break
else:
    raise Exception("No drawing template configured in SolidWorks")
```

A fallback of the form `GetUserPreferenceStringValue(0).replace("Part", "Drawing")` is
worth calling out as a trap: on SW 2025 slot 0 is empty, so the replace runs on `""` and
produces `""`, and the failure surfaces far from its cause.

Found 2026-08-14 while implementing drawing-view placement against live SolidWorks 2025.

---

## 16. `AddComponent5` places nothing unless the component document is already loaded

**Symptom:** the call returns a component object, the assembly is unchanged, and nothing
raises.

**Root cause:** two independent failures that look identical.

1. The component document must be open in memory before it can be inserted. `OpenDoc6`
   has to run first.
2. `OpenDoc6`'s `errors`/`warnings` out-parameters must be **byref VARIANTs**. Passing
   `pythoncom.Missing` makes it return `None`, the document stays unloaded, and every
   `AddComponent` overload then does nothing — while still handing back a component
   object, so the return value looks like success. (Runbook item 1 in `CLAUDE.md` at the
   repository root recommends `pythoncom.Missing` for `OpenDoc6`; that works for opening a
   document to read it, but not on this path.)

A third cause produces the same silence: SolidWorks refuses to insert a part with no
solid body, again without raising.

**Fix:** load first with byref out-params, then verify by component count rather than by
the return value:

```python
def _byref_int():
    return win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

opened = app.OpenDoc6(path, doc_type, 1, "", _byref_int(), _byref_int())
if not opened:
    raise Exception(f"Could not load {path!r} — OpenDoc6 returned nothing.")

before = len(assembly.GetComponents(True) or ())
assembly.AddComponent5(path, 0, "", False, "", x_m, y_m, z_m)
after = len(assembly.GetComponents(True) or ())
if after <= before:
    raise Exception("Component was not inserted — check the part has a solid body.")
```

Found 2026-08-14 while implementing assembly component insertion against live
SolidWorks 2025.

---

## 17. Use `AddMate5` on SW 2025, not `AddMate3`

**Symptom:** older mate examples and third-party plans call `IAssemblyDoc::AddMate3`.

**What works:** `AddMate5` — 15 arguments, with `ErrorStatus` as a byref out-parameter
(use the same `_byref_int()` helper as #16). Verified live on SW 2025 by confirming the
mate moved geometry, not by its return value: snapshot every component's
`IComponent2::Transform2` before and after and compare. SolidWorks accepts a mate it then
ignores, so the return value alone does not tell you whether anything moved.

Found 2026-08-14 while implementing assembly mates against live SolidWorks 2025.

---

## 18. `InsertModelAnnotations3` inserts nothing — resolved

**Status: resolved 2026-10-17 on SW 2025.** Live-verified working sequence (used by
`insert_model_dimensions` in `adapters/solidworks/documentation.py`), per view:

1. `IDrawingDoc::ActivateView(name)`, `ClearSelection2(True)`
2. `SelectByID2(name, "DRAWINGVIEW", 0, 0, 0, False, 0, <VT_DISPATCH null>, 0)` (see #1)
3. `InsertModelAnnotations3(0 /* FromEntireModel */, 32768 | 131072 /* MarkedForDrawing |
   HoleWizardLocations */, False /* AllViews */, False, False, False /* UsePlacementInSketch */)`

`UsePlacementInSketch=False` is the ingredient: with it `True` SolidWorks copies sketch
positions, which on a drawing view lands every dimension *inside* the view outline, on
the part. Judge success from `IView::GetDisplayDimensionCount()` before/after, never from
the return value. Calling per view also imports the same model dimension into several
views; delete repeats (see #30) so each dimension appears once.

The original investigation, kept for reference:

**Symptom:** `IDrawingDoc::InsertModelAnnotations3` returns `None` and no dimensions
appear, on a drawing view of a part that carries a real sketch dimension.
`IView::GetDisplayDimensionCount()` stays `0`.

**What was tried**, all on SW 2025, all returning `None`:

- `Types` as `swInsertDimensions` (8) and as `swInsertDimensionsMarkedForDrawing` (32768),
  and the two OR'd together
- `AllViews` both `True` and `False`
- with the view selected via `SelectByID2(name, "DRAWINGVIEW", …)` — using a
  `VT_DISPATCH` null callout per #1, which is what makes the selection return `True` —
  and then activated with `ActivateView`, following the sequence in the official example
- against both a `*Front` and a `*Top` view, in case the dimension's sketch plane could
  not be shown in the chosen view
- against a part with an explicit sketch dimension added through
  `ISketchManager`, not just an undimensioned profile
- after `ForceRebuild3(True)`
- called raw rather than through a helper that swallows exceptions, confirming it
  genuinely returns `None` rather than raising

**Do not** infer a count from the return value if you get one: the method returns an
**array of inserted `IAnnotation` objects**, so `int(result)` is meaningless and
`len(result)` is the count. A reference implementation read it as an integer and
therefore always computed `0`.

Found 2026-08-14 while implementing drawing annotation against live SolidWorks 2025.

---

## 19. `IModelDoc2.FeatureChamferType` is a silent no-op — feature-count change is not proof of success

**Symptom:** The call returns cleanly (no exception, `VT_VOID`), a real feature named
e.g. `"Chamfer1"` of type `"Chamfer"` appears in the tree, unsuppressed, no error code —
but the model's geometry is byte-identical. No material was actually removed.

**Root cause:** `IModelDoc2.FeatureChamferType(ChamferType, Width, Angle, Flip, OtherDist,
VertexChamDist1, VertexChamDist2, VertexChamDist3)` (DISPID 65888) matches its documented
signature exactly — parameter count, order, and COM types (`VT_I2`, `VT_R8`, `VT_BOOL`) all
check out against the live type library. The edge selection beforehand is also confirmed
correct (`SelectionManager.GetSelectedObjectCount2(-1) == 1` immediately before the call).
The call still does not cut anything. This was confirmed live on SW major 34 (SW2026);
whether it's broken on every "2025+" build or just this one is unknown.

This is a sharper version of pitfall #6/#7's "int, not IFeature" problem: those return an
int you can at least check for `0`/failure. `FeatureChamferType` returns nothing to check
at all, so **"the call didn't raise and the feature count went up" is not evidence the
operation did what it claims.** A reference implementation used exactly that heuristic
(`count_after > count_before`) and reported "success" on every call, always with zero
volume removed.

**Fix:** Use `IFeatureManager.InsertFeatureChamfer` (pitfall #2) unconditionally — do not
version-branch to `FeatureChamferType` at all. Verified on the same SW major 34 install to
actually remove material:

```python
feature = model.FeatureManager.InsertFeatureChamfer(
    1,           # Options
    1,           # ChamferType = equal distance
    width_m,
    math.pi / 4,
    0.0, 0.0, 0.0, 0.0,
)
if not feature:
    raise Exception("InsertFeatureChamfer returned None")
```

**How this was actually confirmed** — feature-tree inspection was not enough; the
diagnostic that caught it compared `IModelDoc2.Extension.CreateMassProperty().Volume`
immediately before and after the call:

```python
mp_before = await adapter.get_mass_properties()
# ... make the FeatureChamferType call ...
mp_after = await adapter.get_mass_properties()
assert mp_after.data.volume < mp_before.data.volume  # was NOT true for FeatureChamferType
```

**General lesson:** for any feature-creation call whose only observable signal is "did the
feature count change" or "did it raise," verify with a geometry-level check (mass
properties volume, or a screenshot) at least once against real SolidWorks before trusting
it. A feature appearing in the tree is necessary but not sufficient evidence the operation
actually did anything.

Found 2026-09-18 while adding a live regression test for the `add_chamfer` MCP tool
against the M4 heat-set-insert coupon (see `tests/live/test_live_sw_add_chamfer_tool.py`).

---

## 20. `SelectByID2` coordinate-based EDGE selection can silently resolve to the *wrong* edge at a shared face boundary — select the FACE instead

**Symptom:** `SelectByID2("", "EDGE", x, y, z, ...)` returns `True` (a "successful" selection),
and the resulting chamfer/fillet reports success with a real volume change — but it's the
*wrong* edge. Worse than pitfall #19: there is no error, no zero-volume tell, nothing to
catch by checking "did the operation report success."

**Root cause:** A point that sits exactly on the boundary shared by two entities — e.g. a
hole's rim edge, which lies exactly in the plane of the flat face it opens into — is
ambiguous input to SolidWorks' nearest-entity resolution. On one part, at one rebuild state,
it may resolve to the hole's circular rim; after literally any other feature is added
earlier in the tree (changing internal tessellation/entity ordering), the exact same
coordinate can resolve to a different, unrelated edge instead (confirmed live: a block's
30mm straight outer edge, ~12mm away in-plane from the intended hole).

**How this was actually caught** — not by checking success/failure, and not by checking
"was some volume removed" (a wrong-edge chamfer still removes real volume). It required
computing the *expected* volume for the specific edge being targeted and comparing:

```python
# Expected volume removed chamfering a circular edge of radius r by width w:
expected_hole_rim = math.pi * (((r + w) ** 3 - r**3) / 3.0 - r * r * w)   # ≈ 2.29 mm³ for r=2.75, w=0.5

# Expected volume removed chamfering ONE straight edge of length L by width w:
expected_straight_edge = 0.5 * w * w * L                                   # = 3.75 mm³ for L=30, w=0.5

# Measured delta matched expected_straight_edge almost exactly (3.7500 mm³) —
# proof the "hole rim" coordinate had actually chamfered the block's outer
# edge instead, despite SelectByID2 returning True and a real Chamfer1
# feature with plausible-looking volume appearing in the tree.
```

A generic feature-defintion inspection (`IFeature.GetDefinition()`) returned `None` for
this feature type under late binding and wasn't useful here — the geometric volume
comparison was the only thing that actually caught it.

**Fix:** For any edge that sits on a shared/ambiguous boundary (a hole's rim flush with a
face, two coplanar edges, etc.), select the **face** instead of hunting for the edge by
coordinate. `InsertFeatureChamfer`/`FeatureFillet3` accept a face selection and apply to
every edge bounding that face — for a hole, that's exactly its one rim edge; for a larger
face, it's every edge on its boundary in one call. A point well inside a face's interior
has no equivalent boundary ambiguity:

```python
model.Extension.SelectByID2("", "FACE", x, y, z, False, 0, null_callout, 0)
feature = model.FeatureManager.InsertFeatureChamfer(1, 1, width_m, math.pi / 4, 0.0, 0.0, 0.0, 0.0)
```

This project's adapter (`_parse_edge_spec` in `features.py`) now supports a `"face:x,y,z"`
prefix in `add_chamfer`/`add_fillet`'s `edge_names` for exactly this reason — prefer it
over a coordinate that lands on a shared boundary.

**General lesson:** "the operation reported success and did something plausible" is still
not proof it did the *intended* thing when the target was selected by nearest-point
coordinate. If the edge/face could plausibly be confused with a neighbor (shared boundary,
similar size, similar location), verify against a geometry-derived expected value, not just
a before/after delta.

Found 2026-09-18, same investigation as pitfall #19, after fixing that bug and finding this
second, independent one immediately behind it.

---

## 21. `SaveBitmapWithVariableSize` captures whatever MDI window is frontmost, not the COM object it's called on

**Symptom:** `export_image` reports success and writes a real image file, but the picture is
of a *different* open SolidWorks document than the one the adapter targeted — e.g. the
user's unrelated real project, captured instead of the script's own test part.

**Root cause:** `IModelDoc2::SaveBitmapWithVariableSize` / `IModelView2::SaveBitmapWithVariableSize`
render the currently-visible MDI child window inside the SW frame, not necessarily the
document identified by the COM object the method is invoked on. `swApp.Frame.SetFocus()`
only focuses the top-level SW application window — it does nothing to select *which* of
several open document tabs/windows is the active one. If the user has clicked into a
different document in the SW UI between when the adapter captured its `currentModel`
reference and when `export_image` actually runs, the bitmap comes from whatever they were
last looking at, silently, with no error.

**Fix:** explicitly activate the target document's own window with `ISldWorks::ActivateDoc3`
before capturing, using its title (not path):

```python
title = target_doc.GetTitle()
# Option 1 = swDontRebuildActiveDoc, then EditRebuild3: no SolidWorks window
# (0 shows a rebuild prompt, 2 a "Loading..." dialog; see #38). io.activate_doc does this.
swApp.ActivateDoc3(title, False, 1, byref_long_out_param)
swApp.Frame.SetFocus()
# ... then capture (SaveBMP; SaveBitmapWithVariableSize does not exist, see #34)
```

`export_image` in `pywin32_adapter.py` now does this unconditionally before every capture.

**General lesson:** a COM method called "on" a specific document object is not guaranteed to
operate on that document if the underlying operation is actually frame/window-scoped rather
than document-scoped. When in doubt, activate the document explicitly first rather than
trusting that holding a reference to it is enough.

Found 2026-09-18, flagged during the add_chamfer live demo (screenshot twice showed the
user's real project instead of the test coupon) but not fixed at the time; fixed in a
follow-up pass the same day.

---

## 22. `add_fillet`/`add_chamfer` unconditionally cleared the user's live UI selection, even with `edge_names=[]`

**Symptom:** The user hand-selects several edges in the SolidWorks UI (e.g. the outer edges
of a block plus a hole rim) and asks for a fillet on "the edges I have selected" — the
resulting fillet only covers one of them (typically whichever edge SW's own no-selection
fallback happened to land on), not the full set the user picked.

**Root cause:** `_add_fillet_impl`/`_add_chamfer_impl` called
`adapter.currentModel.ClearSelection2(True)` *unconditionally* at the top of the operation,
before checking whether `edge_names` was even non-empty. `edge_names=[]` is documented as
"use the current selection / fillet all edges", but the unconditional clear wiped out
exactly the selection that meant "use the current selection" — by the time `FeatureFillet3`
ran, nothing was selected at all, so SW fell back to its own all-edges (or first-found-edge)
behavior instead of the user's actual picks.

**Fix:** only clear and rebuild the selection when `edge_names` is non-empty — i.e. when the
caller is explicitly naming edges/faces to select. An empty list now leaves whatever is
already selected in the live UI completely untouched:

```python
if edge_names:
    model.ClearSelection2(True)
    for name in edge_names:
        ...  # SelectByID2 / _select_edge_by_coord as before
# else: fall through to FeatureFillet3/InsertFeatureChamfer on the existing selection
```

Combined with `get_selected_entities` (added the same day — see the selection mixin), this
gives a coordinate-free path for "operate on exactly what the user selected": read the
selection to show the agent what's there, then call `add_fillet(radius, edge_names=[])`
without ever re-selecting anything, sidestepping the coordinate-ambiguity bugs in #20
entirely for this case.

**General lesson:** a "no-op" input value (empty list, `None`, etc.) can still trigger a
side-effecting call earlier in the function. Audit unconditional setup/teardown calls
(`ClearSelection2`, `EditRebuild3`, etc.) against every branch that follows, not just the
branch you're currently changing.

Found and fixed 2026-09-18.

---

## 23. `get_mass_properties`'s `ForceRebuild3` call silently clears the live UI selection

**Symptom:** A workflow that reads the current selection, measures something (e.g. mass
properties, for a before/after volume comparison), then acts on "the current selection"
(e.g. `add_fillet(edge_names=[])`, see pitfall #22) ends up creating an empty/near-empty
feature — the measurement step ran *between* reading the selection and using it, and wiped
it out.

**Root cause:** `get_mass_properties`'s `_get()` closure (`solidworks/io.py`) starts with
`adapter.currentModel.ForceRebuild3(False)`. Forcing a model rebuild is a well-known
selection-clearing operation in SolidWorks — the tessellation/topology being regenerated
invalidates any transient entity selection, so `ForceRebuild3` silently deselects everything
in the live UI as a side effect of "just measuring."

**Fix:** don't call `get_mass_properties` (or anything else that rebuilds the model) between
reading a selection you intend to reuse and acting on it. If you need a before/after volume
comparison around a selection-consuming operation, take the "before" measurement *first*,
before ever reading the selection with `get_selected_entities`, not immediately before the
feature call.

**General lesson:** a "read-only sounding" diagnostic call (measuring mass properties) can
still mutate transient UI state (selection) as an incidental side effect of a step it needs
internally (forcing a rebuild for accurate measurements). When chaining "read selection →
act on selection," audit every call placed in between for rebuild/regenerate semantics, not
just calls that obviously write geometry.

Found 2026-09-18 while live-verifying the pitfall #22 fix: a `get_mass_properties` call placed
between reading a 4-edge UI selection and calling `add_fillet(edge_names=[])` cleared the
selection, and the resulting fillet reported "success" with a real feature name but removed
0.0000 mm³ — the same silent-success shape as pitfall #19, but here caused by test-script
ordering rather than a product bug in `add_fillet` itself.

---

## 24. `IEntity.Select4` needs a real `SelectData` — `None` is a type mismatch

**Symptom:** `edge.Select4(False, None)` raises `(-2147352571, 'Type mismatch.', None, 2)`
and nothing is selected.

**Root cause:** the second parameter is an `ISelectData` dispatch. Python `None`
marshals as `VT_NULL`, which SolidWorks rejects — the same family as pitfall #1
(`SelectByID2`'s `Callout`).

**Fix:** create one from the selection manager and reuse it for every entity:

```python
sel_mgr = model.SelectionManager            # flag CreateSelectData / GetSelectedObjectCount2
data = sel_mgr.CreateSelectData()
model.ClearSelection2(True)                 # unless appending
for edge in face.GetEdges():                # flag Select4 on each edge
    edge.Select4(True, data)                # True = append to the set being built
```

Also note, from the same investigation: every `IBody2`/`IFace2`/`IEdge`/`ICurve`
dispatch must be method-flagged (pitfall #5) — unflagged, `GetEdges`/`GetArea`/
`IsPlane` return their *value* (`'tuple' object is not callable`) and `GetSurface`
is `Member not found`. `IFace2.Normal` is a property and is `[0, 0, 0]` for
non-planar faces; a full-circle edge (hole rim) has no start/end vertex, so describe it
with `ICurve.CircleParams` (`[cx, cy, cz, ax, ay, az, radius]`, metres).

Found 2026-10-13 building `select_face_edges` (#106).

---

## 25. Array/bool out-parameters (`GetWhatsWrong`, `GetErrorCode2`) need byref VARIANTs

**Symptom:** `ext.GetWhatsWrong()` and `feature.GetErrorCode2()` raise
`'Parameter not optional.'`; passing `pythoncom.Missing` raises
`Objects of type 'PyOleMissing' can not be converted to a COM VARIANT`.

**Fix:** pass byref VARIANTs and read `.value` afterwards (works under forced late
binding — no early-bound wrapper needed, and `makepy` cannot auto-generate one for these
objects anyway):

```python
from win32com.client import VARIANT
import pythoncom

feats, codes, warns = (VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None) for _ in range(3))
ext.GetWhatsWrong(feats, codes, warns)        # feats.value: tuple of IFeature, codes.value: swFeatureError_e
is_warning = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
code = feature.GetErrorCode2(is_warning)      # is_warning.value: bool
```

`_byref_variant()` / `_byref_bool()` in `solidworks/io.py` build these (with a
non-pywin32 fallback). `swFeatureError_e` values are generated from `swconst.tlb` by
`scripts/gen_sw_feature_errors.py` — never hand-type them (see #60).

**Gotchas observed:** an extrude whose sketch was emptied reports code `1`
(`swFeatureErrorUnknown`), so the code alone is often unhelpful — `rebuild_model` falls
back to the feature type and checks parent sketches for zero segments. And setting a
fillet's radius dimension to an impossible value (30 / 200 mm on a 10 mm block) via
`SetSystemValue3` + `EditRebuild3` produced **no** reported rebuild error at all.

Found 2026-10-13 building `rebuild_model` diagnostics (#106).

---

## 26. SolidWorks 2026 SP04 (3DEXPERIENCE) crashes in its idle-time CommandManager refresh

- **Signature:** SolidWorks dies during or right after an ordinary call
  (`CreateLine`, `CloseDoc`, ...); the client gets RPC `0x800706BE`. The
  journal (`%APPDATA%\SolidWorks\SOLIDWORKS 2026\swxJRNL.BAK` after a
  restart) ends with a stack trace in SolidWorks' own idle loop:
  `CAmApp::OnIdle` -> `swCMBar::SetAnalysisPreparationTabVisibility` ->
  `uiBlockMan_c::isPartialModify` -> `uiModelDoc_c::conditionalBlockCmd`.
  Windows Error Reporting records nothing.
- **Not our code:** `main` crashes identically, and a COM trace showed the
  feature branch sending byte-identical calls. Not a leak (memory/GDI flat).
- **When:** nearly every crash landed 2-5 minutes after SolidWorks launched,
  while 3DEXPERIENCE finishes signing in and re-lays-out its role-based
  CommandManager tabs, combined with back-to-back API calls.
- **What works (2026-10-20):** the full live regression file ran clean on a
  warmed-up session at 1 s per call, 2.5 s per document open/create/close and
  8 s between tests. `_handle_com_operation` now pauses after every operation
  (`SOLIDWORKS_MCP_COM_SETTLE_SECONDS`, default 0.25;
  `SOLIDWORKS_MCP_DOC_SETTLE_SECONDS`, default 1.0). The live suite applies the
  slower values and waits until SolidWorks is `SW_TEST_WARMUP_SECONDS` (480)
  old before its first test.
- **Did not help:** `ISldWorks.CommandInProgress` (crashed sooner),
  `SketchManager.AddToDB`, leaving sketch-edit mode before `CloseDoc`,
  unloading the 3DEXPERIENCE add-ins, resetting SolidWorks settings, hidden
  background mode (`DocumentVisible(False)` stops sketch creation entirely),
  and restarting SolidWorks every N documents (the 3DEXPERIENCE edition will
  not relaunch from `sldworks.exe` directly).
- **Harness rule:** after a crash, `connect()` would COM-launch a bare
  `SLDWORKS.exe -Embedding` per test and crash it again. The live fixtures now
  stop the run when SolidWorks is not running. Use `-x` for live runs.

## 27. `ICustomPropertyManager::Get6` raises "Parameter not optional"; `GetNames` is a property

Under late binding `Get6(name, False)` raises `(-2147352561, 'Parameter not optional.')`
because of its four out-parameters, and `Get5`/`Get4`/`GetAll3` do the same. `Get(name)`
returns the stored text. `GetNames` comes back as a tuple *property*, so calling it raises
`'tuple' object is not callable`; read it with `_get_attr_or_call`.

## 28. `IDimension::FullName` includes the document: `D1@Sketch1@Part1.Part`

The trailing `@<document title>` is not part of the name `IModelDoc2::Parameter` (behind
`set_dimension`) accepts. Strip the last segment when it contains a `.`.

## 29. `swFileLocationsMaterialDatabases` lists only the custom material folders

`GetUserPreferenceStringValue(28)` returned `""` on a SW 2025 install whose libraries
exist, and only `C:\ProgramData\SolidWorks\SOLIDWORKS 2026\Custom Materials`
(one material) on SW 2026: it lists the folders the user added, never the built-in
library. Always read the built-in folder as well: `<GetExecutablePath() folder>\lang\<GetCurrentLanguage()>\sldmaterials`
(`GetExecutablePath` may include the `.exe`; take its folder). The `.sldmat` files are
UTF-16 XML: `<classification name>` elements holding `<material name>` children.

## 30. `IAnnotation::Select3` selects nothing under late binding

`Select3(False, <VT_DISPATCH null>)` returns `False` and `Select3(False, None)` raises a
type mismatch. To delete a drawing dimension, take
`IDisplayDimension::GetNameForSelection()` (e.g. `D1@Sketch1@Part1-2@Drawing View2`),
`SelectByID2(that, "DIMENSION", …)`, then `IModelDocExtension::DeleteSelection2(0)`.

---

## 31. `IView.Position = (x, y)` silently moves the view to x ≈ 1e-310

**Symptom:** Setting a drawing view's `Position` from a Python tuple returns cleanly, but
reading it back gives `(6.95e-310, y)`: x is garbage, so the view lands off the left edge
of the sheet. Any layout code that trusts the assignment then "fixes" overlaps by
shrinking the scale, forever.

**Fix:** pass an explicit `win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
[x, y])`, then read `Position` back to confirm. The same applies to `IView.ScaleRatio`.
Live-verified on SW 2025 (`_double_array` / `_set_view_position` in
`adapters/solidworks/drawing_standard.py`).

---

## 32. New drawings can block every COM call behind a "Sheet Format/Size" dialog

When the drawing template has no sheet format, `NewDocument` opens a modal *Sheet
Format/Size* dialog and every later COM call hangs until a person dismisses it. Turn off
`swDrawingShowSheetFormatDialog` (user-preference toggle **353**) around `create_drawing`,
restore it after, then apply a format with `IDrawingDoc::SetupSheet5`. Find the `.slddrt`
through `swFileLocationsSheetFormat` (string preference 7); on a default install the files
live under `C:\ProgramData\SOLIDWORKS\SOLIDWORKS <year>\lang\<language>\sheetformat`,
not under the install folder.

---

## 33. `CreateMassProperty().Volume` is empty while a sketch or plane is selected

`IModelDocExtension::CreateMassProperty` computes for the current selection. With a
sketch selected (the state every extrude, revolve and cut runs in) its `Volume` came back
unreadable both before and after the feature on SW 2026, so a before/after comparison
saw nothing. `get_mass_properties` hides this with `ForceRebuild3`, which clears the
selection (#23). To read a part's volume without touching the selection, sum
`IBody2::GetMassProperties(density)[3]` (m³) over `IPartDoc::GetBodies2(swSolidBody,
False)`. `GetBodies2` answers null, not an empty array, on a part with no bodies yet:
treat null without an exception as zero bodies.

`IBody2::GetExtremePoint(dx, dy, dz, x, y, z)` with byref-double out-params worked as
written under late binding, giving exact sizes on a Ø20 cylinder where `GetPartBox`
agreed. Both live-verified 2026-10-30 (`get_model_geometry_summary` in
`adapters/solidworks/io.py`, `tests/live/test_live_sw_verify_model.py`).

---

## 34. Coordinate picks, face fillets, and image size: three silent no-ops

**`SelectByID2("", "EDGE", x, y, z, ...)` picks along the view direction.** It is a
screen pick through the point, not "the edge nearest the point": on a 12 mm plate seen
from the front, the midpoint of an edge at z=-6 selected the matching edge at z=+6 in
front of it. A 28-edge fillet missed 4 back edges this way, reporting success. Coordinate
specs are now resolved by walking `IPartDoc::GetBodies2` → `IBody2::GetEdges` /
`GetFaces` and taking the entity with the smallest distance from the point to
`IEdge::GetClosestPointOn` / `IFace2::GetClosestPointOn` (first three values), then
`IEntity::Select4(append, SelectData)` with `SelectData.Mark` set. A point more than
0.5 mm from every edge is refused instead of picking a neighbour. Vertices are not walked:
a corner lies on its edges at distance 0, so the walk would pick an edge (opposite corners
of a 40×20×12 block measured 44.72 mm, edge to edge, instead of 46.19 mm). A `VERTEX`
spec keeps the `SelectByID2` pick.

**`IModelDoc2::FeatureFillet3` (SW 2025+) returns non-zero for a selected face but builds
nothing**: no feature, no volume change. Select the face's edges (`IFace2::GetEdges`)
instead. Its return code proves nothing either way, so `add_fillet` checks that
`GetFeatureCount` grew and that the volume changed.

**`SaveBitmapWithVariableSize` does not exist** in the SW 2026 type library, and neither
does `IModelView::ZoomToFit`; `export_image` silently fell through to `SaveAs3`, which
always writes the window's size. `IModelDoc2::SaveBMP(path, width, height)` renders at a
given size but keeps the window's framing, so render at the window's aspect
(`IModelView.FrameWidth` / `FrameHeight`) and pad out to the requested size. Zoom is
`IModelDoc2::ViewZoomtofit2` (lower-case "tofit"; `ViewZoomToFit2` is not in the method
map, so late binding treats it as a property read).

`SolidWorksFeaturesMixin.add_fillet`, `_BodyEntityPicker` in `adapters/solidworks/features.py`
and `_save_screenshot_sized` in `pywin32_adapter.py`. Live-verified on SW 2026,
2026-10-31.

---

## 35. One-way `FeatureCut4`: `Sd` means "single direction", and the normal may point away

**Symptom:** a blind or Through All `create_cut_extrude` returns no feature and no COM
error.

**What the arguments do** (probed live on SW 2026, 2026-11-01, one fresh part per case):

- `Sd` (1st argument) is "single direction". `True` cuts Direction 1 only. `False`
  also cuts Direction 2 with `T2`/`D2`; with `D2=0` that second side has zero depth.
- `Dir` (3rd argument) `False` is SolidWorks' cut default and goes *against* the sketch
  normal (from a face, into the part); `Dir=True` goes along it. `FeatureExtrusion3` is
  the other way round: `Dir=False` grows a boss *along* the normal. So the same `Dir`
  sends a boss and a cut to opposite sides of their sketch plane.

| Ø5.5 × 6 mm hole, Top Plane sketch under a block extruded up from Top | Result |
|---|---|
| `Sd=False`, `D2=0` (what the adapter sent on SW 2025+ since 69d3dbd) | no feature |
| `Sd=True`, `Dir=False` | no feature: `Dir=False` cuts against the normal, away from the block |
| `Sd=True`, `Dir=True` | cuts exactly 142.55 mm³ |
| `Sd=True`, then `Sd=False` on the same sketch | no feature (a failed call does not spoil the retry; `Sd=False` just never works here) |

From a sketch on a plane through the middle of a body (Front Plane of a mid-plane
block), `Sd=True` cuts in either direction and `Sd=False` with `D2=0` returns nothing.

**Why it looked fine before:** on main the `FeatureCut4` call failed and the
`FeatureCut3` fallback passed `D2 = depth` with `Sd=False`, a double-ended cut whose
second side happened to go into the block. Fixing that fallback's arguments (#192)
removed the accident and exposed the real problem.

**Fix:** a one-way cut is single-ended (`Sd=True`). A `reverse_direction` the caller
sets is passed to `Dir` unchanged (true: along the normal). If that builds nothing,
retry once with `Dir` reversed, reselecting the sketch first. The result's
`parameters.direction_flipped` (and the tool reply's `cut_extrude.direction_flipped`)
says when that happened. When neither direction builds anything, the error says what
was tried and is classified `feature_not_built`. The SW version picks only
`OptimizeGeometry`, never `Sd`.

**Flipping only when nothing builds is not enough** when the caller leaves the direction
to the server. From an offset plane with a little material on the far side, the cut
builds there and takes a sliver: 1.13 mm³ instead of the 9.05 mm³ meant (DishRack
session, 2026-11-10). So with `reverse_direction` unset, the adapter:

1. cuts along the normal (the side `create_extrusion` grows into) and measures;
2. deletes that cut, cuts against the normal and measures again;
3. keeps the side that removed more. A tie keeps the along-normal side, rebuilt under
   its first name.

The result's `parameters.direction_choice` and `volume_removed_mm3` say what was
compared.

`_create_cut_extrude_impl` and `_create_cut_extrude_choosing_side` in
`adapters/solidworks/features.py`; issue #193.

---

## 36. `swSaveAsOptions_Silent` is 1, not 2; and `Save3(1, None, None)` falls back to a dialog

**Values** (`swconst.tlb`, SW 2026): `Silent` = 1, `Copy` = 2, `SaveReferenced` = 4. The
export calls passed `2` as "Silent", so every export ran as Copy without Silent and could
show a dialog. They now pass `Silent | Copy` (3, `_EXPORT_OPTIONS` in `pywin32_adapter.py`).

**Save in place:** `Save3(Options, Errors, Warnings)` has two by-ref `long`
out-parameters. Passing `None` for them fails under late binding, and the code then fell
back to the legacy `IModelDoc2.Save()`, which isn't silent. Pass `_byref_int()` VARIANTs
and read `.value` afterwards; the bits are `swFileSaveError_e` / `swFileSaveWarning_e`
(`flag_names` in `adapters/solidworks/saving.py` names them).

**Save As:** `IModelDoc2.SaveAs3(Name, Version, Options)` returns `0` on success, else the
`swFileSaveError_e` flags.

**Assemblies:** see #37.

---

## 37. Saving an assembly with modified parts shows "Save Modified Documents"

**Symptom:** after a part of an open assembly changes, saving the assembly in place (the
old `save_file` fallback to `Save()`) or `close_model(save=True)` (`Save`) opens a modal
"SOLIDWORKS Design" dialog asking whether to save the modified documents. The COM call
blocks until someone answers, and nothing is written. Saving the assembly *as a new name*
(`SaveAs3(path, 0, 0)`) didn't ask. Measured on SW 2026 SP4.1,
`tests/scripts/probe_minimized.py --saves`.

**Fix:** `Save3(Silent | SaveReferenced, errors, warnings)` writes the assembly and its
modified parts without a dialog. Because that overwrites part files, `save_document`
first walks `IAssemblyDoc.GetComponents(False)` → `IComponent2.GetModelDoc2` →
`GetSaveFlag` / `GetPathName` / `IsVirtual`. A modified file that existed before this
session, and that the session didn't create or first save, needs the caller's
`overwrite_modified_references`. Without it the save writes nothing and returns
`confirmation_required` with the files. `CloseDoc` on a modified document closes it
without asking.

---

## 38. A minimized SolidWorks: what restores it, who gets the focus, and `SaveBMP`

Measured on SW 2026 SP4.1 (`tests/scripts/probe_minimized.py`):

- **What restores it:** `NewDocument` (`create_part`, `create_assembly`) and activating an
  assembly whose parts changed. It's restored inside the call and stays restored.
- **Focus:** SolidWorks also takes the foreground and keeps it after it is minimized
  again. `ShowWindow(SW_MINIMIZE)` didn't always pass the focus on. Hand it back with
  `AttachThreadInput` (to the foreground thread) and `SetForegroundWindow`. Right after
  `NewDocument` SolidWorks may be too busy for that to work, so retry a few times, 0.1 s
  apart.
- **What leaves it minimized:** `ISldWorks.Visible = True`, sketches, features, saves,
  `CloseDoc`.
- **`SaveBMP` renders the model while minimized.** The graphics area keeps its last size
  (`IModelView.FrameWidth` / `FrameHeight`), so `export_image` needs no restore.
  `Frame.SetFocus()` would take the user's focus, so it is skipped while minimized.
- **No off-screen restore:** `SetWindowPlacement` moves a rectangle that is wholly off
  screen back onto a monitor, so the window can't be restored off-screen.
- **The rebuild prompt comes from `ActivateDoc3`'s own argument.** In
  `ActivateDoc3(Name, UseUserPreferences, Option, Errors)`, `Option` is a
  `swRebuildOnActivationOptions_e`, used when `UseUserPreferences` is false. Measured on
  a scratch assembly after changing its part:

  | `Option` | What SolidWorks showed | `IModelDocExtension.NeedsRebuild2` after |
  |---|---|---|
  | `0` `swUserDecision` | the rebuild box, at 0.2 s; it took the foreground | 0, once the box dismissed itself |
  | `2` `swRebuildActiveDoc` | a "Loading..." `#32770` dialog, which took the foreground for about 0.5 s | 0 |
  | `1` `swDontRebuildActiveDoc` | nothing | 1 |
  | `1`, then `EditRebuild3` or `ForceRebuild3(False)` | nothing | 0 |

  Changing the user preference `swRebuildOnActivation` (230) instead does nothing, even
  when held for 5 s, and neither does `ForceRebuild3` on the assembly before activating
  it. Call `io.activate_doc` (option `1`, then `EditRebuild3` unless `NeedsRebuild2` is
  0). `EditRebuild3` resolves as a property under late binding, so read it through
  `_get_attr_or_call`.
- **Self-closing message boxes:** activating an assembly whose part changed with option
  `0` shows "Models contained within the assembly have changed. Would you like to rebuild
  the assembly now?" (Yes, No), titled "... (Automatically dismissing in 5 seconds)". The countdown
  appears in the title a moment after the box does, and counts down each second. Re-read
  the title on every check, and leave the box alone until its countdown ends (the
  watchdog gives it at most 30 s). Cancelling it first turns a successful activation into
  an error. Its text is in a control `GetWindowText` can't read across processes; send
  `WM_GETTEXT` (with `SendMessageTimeoutW`).

- **Guarding only the adapter's own operations isn't enough.** In the live regression
  suite a COM call made outside `_handle_com_operation` restored SolidWorks between
  operations. From then on every operation started with a visible window and left it
  up. `MinimizeKeeper` remembers that the user wants it minimized and watches from a
  thread. A restore during a call, or within 2 s of any COM call, is undone; one while
  idle is the user's.

The window code is Win32-only (`adapters/solidworks/window.py`, `dialogs.py`), so it may
run off the COM thread.

---

## 39. A SolidWorks that has exited leaves a dead `swApp`, and `Dispatch` would start a new one

**Signature:** after SolidWorks is closed (or crashes) and started again, every call fails
with `(-2147023174, 'The RPC server is unavailable.', None, None)`
(`RPC_S_SERVER_UNAVAILABLE`). The proxy still points into the old process. The new
SolidWorks is never used until something binds to it again.

**What goes wrong when you just reconnect:**

- `win32com.client.Dispatch("SldWorks.Application")` (and `dynamic.Dispatch` with the
  ProgID) *starts* SolidWorks when none is running. A user who closed it sees it come
  back. To bind to a running SolidWorks only, use `GetActiveObject`, which fails with
  `MK_E_UNAVAILABLE` when there is none.
- `currentModel`, `currentSketch` and the sketch entity handles are proxies into the old
  process too. Running the call that found the restart on the new SolidWorks would act on
  whatever is active there, maybe the user's own document.
- Calls made through `_attempt` swallow the RPC error and return their default. A dead
  SolidWorks can then look like an empty one (no documents, no features) rather than a
  failure.

**What the adapter does** (`PyWin32Adapter._solidworks_exited`, then
`_ComSessionCoordinator.recover` and `reconnect`):

- Before each outermost call it checks that the connected SolidWorks' frame window still
  exists and belongs to the same process: `IsWindow` and `GetWindowThreadProcessId`,
  Win32 with no COM. Without a frame handle, it reads `RevisionNumber` after a failed call
  and looks for an RPC HRESULT.
- If SolidWorks has exited, it calls `GetActiveObject`, flags `ISldWorks`, checks
  `RevisionNumber` and sets the session up as `connect` does. It doesn't run the call,
  drops the old document handles, and returns an error that classifies as
  `solidworks_reconnected`.
- If the process is the same (only the window changed), the call runs as usual.

---

## 40. STL options: custom resolution is ignored until a tolerance is written

The STL export options are application preferences (`ISldWorks.Get/SetUserPreference*`,
"System Options > Export > STL" in the `swconst` help): `swSTLQuality` (integer 78,
`swSTLQuality_e` coarse 1, fine 2, custom 3), `swSTLDeviation` and `swSTLAngleTolerance`
(doubles 2 and 3), `swExportStlUnits` (integer 211, `swLengthUnit_e`) and
`swSTLBinaryFormat` (toggle 69).

- **Units:** the help gives none for the tolerances. SolidWorks 2026 stores metres and
  radians: a user's 30 degrees read back as `0.5235987755983`.
- **Custom resolution follows the tolerances.** `SetUserPreferenceIntegerValue(78, 3)`
  returns True but reads back unchanged. After writing a deviation or an angle off the
  coarse/fine presets, the same call sticks. Rewriting a preset value doesn't make it
  stick. SolidWorks derives the resolution from the tolerances.
- So `stl_settings.py` writes the tolerances first, doesn't check custom's read-back,
  refuses custom without a tolerance, and restores the user's tolerances before their
  resolution.
- The deviation SolidWorks reports depends on the active document: 6.8e-5 with a 40 mm
  part open, 5.95e-4 with none. Compare before and after with the same document open.
- **Coarse or fine moves the tolerances to their presets.** A user with custom 0.033 mm /
  10 degrees, after an export at coarse, had coarse 0.068 mm / 30 degrees: putting back
  only the resolution doesn't bring custom back, because the tolerances are now on the
  presets. So an export that sets the resolution also keeps the user's tolerances and
  puts them back first (measured 2026-11-12).

Measured 2026-11-11 on SOLIDWORKS 2026 with `probe_stl_quality.py` (every value restored).

- **An assembly splits into one file per component** while `swSTLComponentsIntoOneFile`
  (toggle 72) is off: exporting to `X.stl` wrote `X - Assembly-1 Part-1.STL` and nine
  more, and no `X.stl`, so the export looked failed (seen 2026-11-12 on a user's
  assembly). `export_file` turns the toggle on for an assembly's export and puts the
  user's value back, and names the per-component files when they appear anyway.
  Measured 2026-11-12: with toggle 72 on, a two-part assembly wrote one closed STL
  and the user's value came back.

---

## 41. `AddComponent4`/`AddComponent5` place a component by its centre, not its origin

`IAssemblyDoc::AddComponent4(CompName, ConfigName, X, Y, Z)` puts the component's centre
at `(X, Y, Z)`, not its origin. A part inserted at (0, 0, 0) landed offset by minus its
bounding-box centre, (0, -6.75, +3.7) mm, and every part mated to it followed.

- `insert_component` moves the component afterwards (`placement.py`). `IComponent2.Transform2`
  gets the same rotation with the asked translation, through
  `IMathUtility::CreateTransform` and a `VT_ARRAY | VT_R8` of the 16 `ArrayData` values.
- A fixed component (the first in an assembly is fixed) is floated for the move and
  fixed again, as a script that moved components on SolidWorks 2026 had to do.

- `IMathUtility.CreateTransform` must be flagged as a method first: unflagged, late
  binding reads it as a property and SolidWorks answers "Member not found".

Reported 2026-11-12 by the Cellvis DishRack build. Measured the same day: two copies
of a block whose origin is a corner landed with their origins at (0, 0, 0) and
(50, 0, 10) mm.

---

## 42. `ViewZoomTo2` takes view coordinates

`IModelDoc2::ViewZoomTo2(X1, Y1, Z1, X2, Y2, Z2)` takes its corners in the view's
coordinates. SolidWorks' "Zoom to Region" example multiplies each point by
`IModelView.Orientation3` first.

- The front view's orientation is the identity, so a model box zooms right there.
- In the right view, a box around the +X block zoomed onto the back block. Only the box
  with model X and Z swapped zoomed where meant.
- `zoom_box.py` transforms the box's eight corners (`IMathPoint.MultiplyTransform`) and
  zooms to the box around them.

- `IMathUtility.CreatePoint` and `IMathPoint.MultiplyTransform` must be flagged as
  methods first ("Member not found" otherwise).
- Still open: the picture comes out a few mm off centre horizontally, in the front
  view too (about 1 mm there, about 4 mm for a 12 x 20 mm face in the right view).

Reported 2026-11-12 by the Cellvis DishRack build. Measured the same day: in the
right view a box around the +X face zooms onto that face and fills the picture's
height.

---

## 43. Instant3D extrudes are `"ICE"`, boss and cut alike

`IFeature.GetTypeName2` returns `"ICE"` for an extrude made with Instant3D, whether it is
a boss or a cut. On SolidWorks 2026 that was every Boss-Extrude and Cut-Extrude the
tools made.

- `IFeature.GetTypeName` gives the underlying type ("the underlying type of feature of an
  Instant3D feature", per the API help). Compare it case-insensitively: "CUT" has been
  reported.
- `feature_editing.feature_kind` does this. Mapping `"ICE"` to `"Cut"` reported bosses as
  cuts.

Found 2026-11-11/12 on SOLIDWORKS 2026 (first live run; Cellvis DishRack).

---

## 44. A part loaded only by an assembly has no window, and `ActivateDoc3` can't activate it

`ISldWorks.GetDocuments` lists every loaded document, including a part an assembly
loaded as a component.

- Such a part is not visible (`IModelDoc2.Visible` False). `ActivateDoc3` on its title
  leaves the last document active.
- Opening its file with `OpenDoc6` (silent) gives it a window, and then it activates.
  `activate_document` (and every tool's `document` argument) does that first
  (`io._open_window`).

Reported 2026-11-12 by the Cellvis DishRack build. Measured the same day: a part whose
window was closed while its assembly stayed open was listed with `Visible` False,
and `activate_document` opened and activated it.

---

## 45. A sketch exited with nothing in it is deleted

Deleting every entity of an open sketch (`delete_sketch_entities` with `all`) and
then exiting it removes the sketch: `edit_sketch` on its name then finds no such
feature. To replace a sketch's contents, draw the new entities before
`exit_sketch`.

Measured 2026-11-12 on SOLIDWORKS 2026 (live test
`test_live_sw_dishrack_fixes.py::test_a_whole_sketch_is_emptied`).

---

## Adapter wiring traps — not COM, same silent-failure shape

These are not SolidWorks issues, but they fail the same way: the code imports, the tests
pass, and the thing you wrote never runs.

### A method written at module scope in a mixin file is unreachable

`adapters/solidworks/io.py` defines `SolidWorksIOMixin`. A method accidentally left at
module scope — one indentation level out — still imports cleanly, still passes every
mock-adapter test, and still satisfies "does this capability exist on every layer" checks.
But `PyWin32Adapter` then resolves the name to `SolidWorksAdapter`'s "not implemented"
default, so every call returns that error and the COM implementation never executes.

Nothing in a normal test run catches this. Assert the owning class directly:

```python
owner = next(
    (klass.__name__ for klass in PyWin32Adapter.__mro__ if name in vars(klass)),
    None,
)
assert owner == "SolidWorksIOMixin"
```

### `_attempt(..., default=X)` hides the difference between "returned nothing" and "raised"

The adapter's `_attempt` helper swallows the exception and hands back the default, so a
`None` result has two very different meanings. When diagnosing a COM call that "returns
`None`", call it raw and catch explicitly before drawing any conclusion:

```python
try:
    raw = drawing.InsertModelAnnotations3(0, 8, True, True, False, False)
    print("returned", type(raw).__name__, raw)
except Exception as exc:
    print("raised", type(exc).__name__, exc)
```

Both investigations behind #13 and #18 came close to the wrong conclusion because a
swallowed `TypeError` was indistinguishable from a genuine empty result.

---

## Operational: heavy documents can crash SolidWorks — throttle the loop

Not a COM API pitfall, but it kills a batch run the same way: silently, mid-loop.

**Symptom:** a batch that opens/exports/closes many parts runs fine for the small ones,
then on a large part (observed ~1.5–1.7 MB `.SLDPRT`, 70+ features) the export fails —

```text
Failed to export STL: ... STL export failed for <path> (tried Extension.SaveAs2 and SaveAs3)
```

— and `SLDWORKS.exe` itself dies. Every call after that returns
`(-2147023174, 'The RPC server is unavailable.')` and `get_model_info` comes back
all-`null` / `type: "Unknown"`. Reopening SolidWorks does **not** fix it — the adapter
still holds the dead COM pointer (see runbook item #3); the MCP server has to be
restarted to reconnect.

**Why:** back-to-back open → tessellate/export → close with no pause gives SolidWorks no
time to release memory and finish background work between documents. Heavy parts
(multibody, large feature trees, imported geometry) push it over.

**What to do in a batch loop:**

- **Throttle.** Put a real pause (~10 s worked here) between parts — after `close_model`,
  before the next `load_part`. Small parts don't need it; you won't know which are heavy
  up front, so pace the whole loop.
- **Do the heavy files last** and don't retry-storm — if a big part fails its export,
  record it and move on rather than reopening it immediately.
- **Check the file size first.** A `.SLDPRT` over ~1 MB, or a component list with
  imported/multibody parts, is the risk set — widen the pause or skip in an unattended run.
- **Detect the crash and stop.** After a failed export, one `get_model_info` returning
  `type: "Unknown"` with `null` path means the COM handle is gone. Abort the loop and
  surface it — every remaining iteration will just fail. Do not report the run as
  complete.

Found 2026-09-05 doing per-part STL export from an assembly (issue #91 follow-up).

---

## `RunMacro2` — module name must match, and the `.swp` must be binary

`ISldWorks::RunMacro2(FilePathName, ModuleName, ProcedureName, Options, Error)`:

- **`Error` (5th arg) is `VT_BYREF | VT_I4` out**, not a plain int. Under pywin32 late
  binding a bare `0` raises `DISP_E_TYPEMISMATCH` ('Type mismatch.', arg index 5) before
  SolidWorks ever sees the file. Pass a `VARIANT(VT_BYREF|VT_I4, 0)` and read the code
  back from `.value` (`_byref_long` in `pywin32_adapter.py`).
- **The code it writes back is `swRunMacroError_e`** (not in the type library;
  `_SW_RUN_MACRO_ERROR` maps it). `0` = `NoError`. **`22` = `Invalidindex`** — `RunMacro2`
  could not resolve `ModuleName`/`ProcedureName` in the project.
- **SolidWorks names the module `<stem>1`.** `Tools -> Macro -> New` on `sample_macro.swp`
  creates module **`sample_macro1`**. SW's own doc example does the same
  (`RunMacroSub.swp` -> module `RunMacroSub1`). Passing the file stem as `ModuleName`
  gets you error 22. The real name is in the `.swp`'s plaintext `PROJECT` stream as
  `Module=<name>` — `_parse_vb_module_name` reads it from the raw bytes when the file
  starts with the OLE2 magic `D0 CF 11 E0`.
- **A `.swp` `RunMacro2` can run must be a binary OLE compound file.** A hand-written
  text file (even with the right `Attribute VB_Name` line, even renamed `.swp`) is
  rejected with a modal **`Cannot open <path>`** dialog — which *blocks the COM STA
  thread with no timeout* (a 2+ minute hang was observed). To get a runnable `.swp` you
  currently have to author it inside SolidWorks (`Tools -> Macro -> New`, or Edit + Save
  in the VBA IDE). Generating one from source text is an open gap.

Found 2026-09-05 wiring `execute_macro` end-to-end against live SW 2026 (issue #91).

---

## Reference: Where to look things up

| Question | Where to look |
|---|---|
| Which class owns a method? | `gen_py/3.13/83A33D31-*x0x34x0.py` — search `def MethodName` and note the class above it |
| Is a name a method or property? | In gen_py class: `def Name(...)` = method; `"Name": (...)` in `_prop_map_get_` = property |
| What DISPID does a method have? | `InvokeTypes(DISPID, ...)` line in the gen_py method body |
| Does a method return IFeature? | Check return type: `(9, 0)` = VT_DISPATCH (object); `(24, 0)` = VT_I4 (integer) |
| Full COM threading rules | See "COM threading architecture" in [CLAUDE.md](https://github.com/andrewbartels1/SolidworksMCP-python/blob/main/CLAUDE.md) |
| Runbook for live debugging | See "Troubleshooting Runbook" section in [CLAUDE.md](https://github.com/andrewbartels1/SolidworksMCP-python/blob/main/CLAUDE.md) |
