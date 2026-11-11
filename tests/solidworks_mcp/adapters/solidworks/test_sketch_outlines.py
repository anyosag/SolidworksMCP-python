"""Planes, sketch axes, arc direction, outlines and construction geometry.

Covers the parts of ``adapters/solidworks/sketch.py`` added for the Cellvis
dish-rack suggestions: ``create_sketch`` never falls back to another plane
and reports the sketch's axes, ``add_arc`` draws either way round, and
``add_sketch_outlines`` draws whole outlines in one COM operation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import limits, sketch


class _Adapter:
    """The adapter attributes the sketch functions use, with no COM."""

    def __init__(self) -> None:
        self.currentModel: Any = None
        self.currentSketchManager: Any = None
        self.currentSketch: Any = None
        self._sketch_count = 0
        self._last_sketch_name: str | None = None
        self._sketch_entities: dict[str, Any] = {}
        self._sketch_entity_centers: dict[str, tuple[float, float]] = {}
        self._next_id = 1
        self.operations: list[str] = []
        self.selected: list[tuple[Any, bool]] = []

    def _handle_com_operation(self, name: str, callback: Any) -> AdapterResult[Any]:
        self.operations.append(name)
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, callback: Any, default: Any = None) -> Any:
        try:
            return callback()
        except Exception:
            return default

    def _attempt_with_error(self, callback: Any) -> tuple[Any, Any]:
        try:
            return callback(), None
        except Exception as exc:
            return None, exc

    def _reset_sketch_entity_registry(self) -> None:
        self._sketch_entities = {}

    def _register_sketch_entity(self, prefix: str, entity: Any) -> str:
        entity_id = f"{prefix}_{self._next_id}"
        self._next_id += 1
        self._sketch_entities[entity_id] = entity
        return entity_id

    def _select_sketch_entity(self, entity: Any, append: bool) -> bool:
        self.selected.append((entity, append))
        return bool(getattr(entity, "selectable", True))


class _Segment:
    """A sketch segment whose construction flag can be set and read back."""

    def __init__(self, *args: Any, sticky: bool = True) -> None:
        self.args = args
        self.sticky = sticky
        self._construction = False

    @property
    def ConstructionGeometry(self) -> bool:
        return self._construction

    @ConstructionGeometry.setter
    def ConstructionGeometry(self, value: bool) -> None:
        if self.sticky:
            self._construction = value


class _Manager:
    """A sketch manager that records every Create call."""

    def __init__(self, refuse_at: int | None = None, sticky: bool = True) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.refuse_at = refuse_at
        self.sticky = sticky

    def _make(self, kind: str, args: tuple[Any, ...]) -> _Segment | None:
        self.calls.append((kind, args))
        if self.refuse_at is not None and len(self.calls) == self.refuse_at:
            return None
        return _Segment(*args, sticky=self.sticky)

    def CreateLine(self, *args: Any) -> _Segment | None:
        return self._make("line", args)

    def CreateArc(self, *args: Any) -> _Segment | None:
        return self._make("arc", args)


class _Model:
    """A part with the given planes, for create_sketch."""

    def __init__(self, planes: set[str], sketch: Any) -> None:
        self.planes = planes
        self.looked_up: list[str] = []
        self.SketchManager = SimpleNamespace(
            InsertSketch=lambda *_args: sketch, ActiveSketch=sketch
        )
        self.Extension = SimpleNamespace(SelectByID2=lambda *_args: False)
        self.deleted = 0

    def FeatureByName(self, name: str) -> Any:
        self.looked_up.append(name)
        if name in self.planes:
            return SimpleNamespace(Select2=lambda *_args: True)
        return None

    def EditDelete(self) -> None:
        self.deleted += 1


class _Transform:
    """``ISketch.ModelToSketchTransform``: Inverse() gives the sketch-to-model one."""

    def __init__(self, array: list[float]) -> None:
        self._array = array

    def Inverse(self) -> SimpleNamespace:
        return SimpleNamespace(ArrayData=self._array)


#: The sketch-to-model transform of a sketch on the Top Plane, 10 mm up:
#: sketch x -> +X, sketch y -> -Z, normal +Y, origin (0, 0.01, 0) m.
_TOP_10MM = [1, 0, 0, 0, 0, -1, 0, 1, 0, 0, 0.01, 0, 1, 0, 0, 0]


def _sketch_with(array: list[float] | None) -> SimpleNamespace:
    if array is None:
        return SimpleNamespace(Name="Sketch1")
    return SimpleNamespace(Name="Sketch1", ModelToSketchTransform=_Transform(array))


# --- planes -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("plane", "key", "first"),
    [
        ("Front", "front", "Front Plane"),
        ("XY", "front", "Front Plane"),
        ("Top", "top", "Top Plane"),
        ("xz", "top", "Top Plane"),
        ("top plane", "top", "Top Plane"),
        ("YZ", "right", "Right Plane"),
        ("Right Plane", "right", "Right Plane"),
        (" Plane1 ", None, "Plane1"),
    ],
)
def test_plane_names_resolve_to_the_plane_they_name(
    plane: str, key: str | None, first: str
) -> None:
    """XY is the Front Plane in SolidWorks, XZ the Top, YZ the Right."""
    found_key, candidates = sketch.plane_candidates_for(plane)

    assert found_key == key
    assert candidates[0] == first
    if key is None:
        assert candidates == [first]


def test_a_missing_plane_is_an_error_not_a_sketch_on_top() -> None:
    """Regression: a misspelled plane used to be sketched on the Top Plane."""
    adapter = _Adapter()
    adapter.currentModel = _Model({"Top Plane", "Front Plane"}, _sketch_with(None))

    result = sketch._create_sketch_impl(adapter, "Plane7")

    assert result.status == AdapterResultStatus.ERROR
    assert "Plane 'Plane7' not found in the part" in (result.error or "")
    assert adapter.currentModel.looked_up == ["Plane7"]


def test_a_localized_default_plane_is_found_and_reported() -> None:
    adapter = _Adapter()
    adapter.currentModel = _Model({"Planta"}, _sketch_with(None))

    result = sketch._create_sketch_impl(adapter, "Top")

    assert result.is_success
    assert result.data == "Sketch1"
    assert result.metadata is not None
    assert result.metadata["plane"] == "Planta"


# --- sketch axes --------------------------------------------------------------


def test_create_sketch_reports_the_axes_read_from_the_sketch() -> None:
    adapter = _Adapter()
    adapter.currentModel = _Model({"Plane1"}, _sketch_with(_TOP_10MM))

    result = sketch._create_sketch_impl(adapter, "Plane1")

    assert result.is_success
    axes = (result.metadata or {})["axes"]
    assert axes["x"] == [1.0, 0.0, 0.0]
    assert axes["y"] == [0.0, 0.0, -1.0]
    assert axes["normal"] == [0.0, 1.0, 0.0]
    assert axes["origin_mm"] == [0.0, 10.0, 0.0]
    assert axes["summary"] == (
        "sketch x = model +X, sketch y = model -Z, normal = model +Y"
    )


def test_a_default_plane_falls_back_to_its_known_axes() -> None:
    """Without a readable transform, the Right Plane's axes come from the table."""
    adapter = _Adapter()
    adapter.currentModel = _Model({"Right Plane"}, _sketch_with(None))

    result = sketch._create_sketch_impl(adapter, "Right")

    axes = (result.metadata or {})["axes"]
    assert axes["x"] == [0.0, 0.0, -1.0]
    assert axes["y"] == [0.0, 1.0, 0.0]
    assert axes["summary"].startswith("sketch x = model -Z")


def test_another_plane_without_a_transform_has_no_axes() -> None:
    adapter = _Adapter()
    adapter.currentModel = _Model({"Plane1"}, _sketch_with(None))

    result = sketch._create_sketch_impl(adapter, "Plane1")

    assert result.is_success
    assert (result.metadata or {})["axes"] is None


def test_axes_from_a_sloped_plane_name_their_numbers() -> None:
    """A plane at 30 degrees about X: sketch y is not along a model axis."""
    c, s = 0.8660254037844387, 0.5
    axes = sketch.axes_from_transform([1, 0, 0, 0, c, s, 0, -s, c, 0, 0, 0, 1])

    assert axes is not None
    assert axes["y"] == [0.0, 0.866025, 0.5]
    assert "sketch y = model (0, 0.866025, 0.5)" in axes["summary"]


@pytest.mark.parametrize(
    "data",
    [None, "not numbers", [1, 0, 0], [2, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]],
)
def test_unusable_transform_data_gives_no_axes(data: Any) -> None:
    assert sketch.axes_from_transform(data) is None


# --- arcs ---------------------------------------------------------------------


@pytest.mark.parametrize(("direction", "flag"), [("ccw", 1), ("cw", -1)])
def test_an_arc_is_drawn_the_way_it_is_asked(direction: str, flag: int) -> None:
    adapter = _Adapter()
    manager = _Manager()
    adapter.currentSketchManager = manager

    result = sketch._add_arc_impl(adapter, 0, 0, 10, 0, 0, 10, direction)

    assert result.is_success
    assert manager.calls == [("arc", (0.0, 0.0, 0, 0.01, 0.0, 0, 0.0, 0.01, 0, flag))]
    assert adapter._sketch_entity_centers[result.data or ""] == (0, 0)


def test_an_unknown_arc_direction_is_refused() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager()

    result = sketch._add_arc_impl(adapter, 0, 0, 10, 0, 0, 10, "sideways")

    assert result.status == AdapterResultStatus.ERROR
    assert "direction must be 'ccw' or 'cw'" in (result.error or "")


# --- outlines -----------------------------------------------------------------


def _slot() -> list[dict[str, Any]]:
    """A 20 x 10 slot: two lines and two half circles, closed."""
    return [
        {
            "segments": [
                {"type": "line", "start": [0.0, -5.0], "end": [20.0, -5.0]},
                {
                    "type": "arc",
                    "center": [20.0, 0.0],
                    "start": [20.0, -5.0],
                    "end": [20.0, 5.0],
                    "direction": "ccw",
                },
                {"type": "line", "start": [20.0, 5.0], "end": [0.0, 5.0]},
                {
                    "type": "arc",
                    "center": [0.0, 0.0],
                    "start": [0.0, 5.0],
                    "end": [0.0, -5.0],
                    "direction": "ccw",
                },
            ],
            "construction": False,
        }
    ]


def test_an_outline_is_drawn_in_one_operation_in_order() -> None:
    adapter = _Adapter()
    manager = _Manager()
    adapter.currentSketchManager = manager

    result = sketch._add_sketch_outlines_impl(adapter, _slot())

    assert result.is_success
    assert adapter.operations == ["add_sketch_outlines"]
    assert [kind for kind, _ in manager.calls] == ["line", "arc", "line", "arc"]
    assert manager.calls[1][1] == (0.02, 0.0, 0, 0.02, -0.005, 0, 0.02, 0.005, 0, 1)
    data = result.data or {}
    assert data["outlines"] == [
        {"ids": ["Line_1", "Arc_2", "Line_3", "Arc_4"], "construction": False}
    ]
    assert (data["segment_count"], data["line_count"], data["arc_count"]) == (4, 2, 2)
    assert adapter._sketch_entity_centers["Line_1"] == (10.0, -5.0)
    assert adapter._sketch_entity_centers["Arc_2"] == (20.0, 0.0)


def test_a_construction_outline_is_construction_geometry() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager()
    outlines = _slot()
    outlines[0]["construction"] = True

    result = sketch._add_sketch_outlines_impl(adapter, outlines)

    assert result.is_success
    assert all(seg.ConstructionGeometry for seg in adapter._sketch_entities.values())


def test_a_refused_segment_removes_what_the_call_drew() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager(refuse_at=3)
    adapter.currentModel = _Model(set(), None)

    result = sketch._add_sketch_outlines_impl(adapter, _slot())

    assert result.status == AdapterResultStatus.ERROR
    message = result.error or ""
    assert "Outline 1, segment 3 (line from [20.0, 5.0] to [0.0, 5.0])" in message
    assert "was not created" in message
    assert "the segments this call drew were removed again" in message
    assert [append for _, append in adapter.selected] == [False, True]
    assert adapter.currentModel.deleted == 1
    assert adapter._sketch_entities == {}


def test_a_segment_that_raises_names_the_cause() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = SimpleNamespace(
        CreateLine=lambda *_args: (_ for _ in ()).throw(RuntimeError("type mismatch"))
    )

    result = sketch._add_sketch_outlines_impl(adapter, _slot())

    assert "segment 1 (line from [0.0, -5.0] to [20.0, -5.0]) was not created " in (
        result.error or ""
    )
    assert "(type mismatch)" in (result.error or "")
    # Nothing was drawn, so nothing was selected or deleted.
    assert adapter.selected == []


def test_a_failed_cleanup_says_the_segments_stay() -> None:
    adapter = _Adapter()
    manager = _Manager(refuse_at=2)
    adapter.currentSketchManager = manager
    adapter._select_sketch_entity = lambda *_args: False  # type: ignore[method-assign]

    result = sketch._add_sketch_outlines_impl(adapter, _slot())

    assert "1 segments this call drew stay in the sketch" in (result.error or "")


def test_a_failed_delete_says_the_segments_stay() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager(refuse_at=2)
    adapter.currentModel = SimpleNamespace(
        EditDelete=lambda: (_ for _ in ()).throw(RuntimeError("busy"))
    )

    result = sketch._add_sketch_outlines_impl(adapter, _slot())

    assert "stay in the sketch; undo or delete them" in (result.error or "")
    assert "Line_1" in adapter._sketch_entities


def test_geometry_that_will_not_become_construction_is_removed() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager(sticky=False)
    adapter.currentModel = _Model(set(), None)
    outlines = _slot()
    outlines[0]["construction"] = True

    result = sketch._add_sketch_outlines_impl(adapter, outlines)

    assert "was drawn but could not be made construction geometry" in (
        result.error or ""
    )
    assert adapter.currentModel.deleted == 1


@pytest.mark.parametrize(
    ("outlines", "manager", "message"),
    [
        (_slot(), None, "No active sketch"),
        ([{"segments": []}], _Manager(), "outlines contain no segments"),
        (
            [
                {
                    "segments": [{"type": "line", "start": [0, 0], "end": [1, 0]}]
                    * (sketch.MAX_OUTLINE_SEGMENTS + 1)
                }
            ],
            _Manager(),
            "the most is 2000",
        ),
    ],
)
def test_outlines_refused_before_drawing(
    outlines: list[dict[str, Any]], manager: Any, message: str
) -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = manager

    result = sketch._add_sketch_outlines_impl(adapter, outlines)

    assert result.status == AdapterResultStatus.ERROR
    assert message in (result.error or "")
    assert adapter.operations == []


# --- construction geometry ----------------------------------------------------


def test_a_rectangle_becomes_construction_geometry_on_all_four_lines() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager()
    lines = tuple(_Segment() for _ in range(4))
    adapter._sketch_entities = {"Rectangle_1": lines, "Line_2": _Segment()}

    result = sketch._set_sketch_construction_impl(adapter, ["Rectangle_1", "Line_2"])

    assert result.is_success
    assert result.data == {
        "entity_ids": ["Rectangle_1", "Line_2"],
        "segment_count": 5,
        "construction": True,
    }
    assert all(line.ConstructionGeometry for line in lines)


def test_construction_can_be_turned_off_again() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager()
    line = _Segment()
    line.ConstructionGeometry = True
    adapter._sketch_entities = {"Line_1": line}

    result = sketch._set_sketch_construction_impl(adapter, ["Line_1"], False)

    assert result.is_success
    assert line.ConstructionGeometry is False


def test_construction_that_does_not_take_is_an_error() -> None:
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager()
    adapter._sketch_entities = {"Line_1": _Segment(sticky=False)}

    result = sketch._set_sketch_construction_impl(adapter, ["Line_1"])

    assert "SolidWorks did not make Line_1 construction geometry" in (
        result.error or ""
    )


def test_construction_needs_a_sketch_and_known_ids() -> None:
    adapter = _Adapter()
    assert "No active sketch" in (
        sketch._set_sketch_construction_impl(adapter, ["Line_1"]).error or ""
    )
    adapter.currentSketchManager = _Manager()
    missing = sketch._set_sketch_construction_impl(adapter, ["Line_9", "Arc_3"])
    assert "Sketch entity Line_9, Arc_3 not found in the open sketch" in (
        missing.error or ""
    )


def test_segments_of_skips_empty_slots() -> None:
    first = _Segment()
    assert sketch._segments_of((first, None)) == [first]
    assert sketch._segments_of(first) == [first]


# --- the mixin forwards -------------------------------------------------------


@pytest.mark.asyncio
async def test_the_mixin_forwards_the_new_methods() -> None:
    class _Mixed(sketch.SolidWorksSketchMixin, _Adapter):
        pass

    adapter = _Mixed()
    adapter.currentSketchManager = _Manager()

    drawn = await adapter.add_sketch_outlines(_slot())
    assert drawn.is_success
    assert (await adapter.set_sketch_construction(["Line_1"])).is_success
    assert (await adapter.add_arc(0, 0, 5, 0, 0, 5, "cw")).is_success


def test_a_stopped_outline_removes_what_the_call_drew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Out of time at segment 3: the two segments drawn are deleted again."""
    adapter = _Adapter()
    adapter.currentSketchManager = _Manager()
    adapter.currentModel = _Model(set(), None)
    checks: list[str] = []

    def check(doing: str) -> None:
        checks.append(doing)
        if len(checks) == 3:
            raise limits.OperationStopped(f"Stopped {doing} after 901 s: limit")

    monkeypatch.setattr(limits, "check", check)

    result = sketch._add_sketch_outlines_impl(adapter, _slot())

    assert result.status == AdapterResultStatus.ERROR
    message = result.error or ""
    assert message.startswith("Stopped drawing outline 1, segment 3 after 901 s")
    assert "the segments this call drew were removed again" in message
    assert adapter.currentModel.deleted == 1
    assert adapter._sketch_entities == {}
