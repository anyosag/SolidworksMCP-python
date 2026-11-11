"""Which side a one-way cut goes, and how a cut left without a direction picks it.

A boss (``FeatureExtrusion3``, ``Dir=False``) grows along the sketch normal; a
cut (``FeatureCut4``, ``Dir=False``) goes against it. A cut's
``reverse_direction`` is passed as ``Dir`` unchanged, so recorded calls cut as
they did: True along the normal, False against it, and the other side once
when that one builds nothing. A cut left without a direction starts along the
normal, measures both sides and keeps the one that removes more (a cut on an
offset plane took a 1.13 mm³ sliver when 9.05 mm³ was on the other side).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    ExtrusionParameters,
)
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter
from solidworks_mcp.adapters.solidworks import features

_VOLUME = 1000.0


class _Cut:
    """A cut feature in :class:`_Part`; renaming it renames it in the tree."""

    def __init__(self, part: _Part, name: str, removed: float) -> None:
        self._part = part
        self._name = name
        self.removed = removed

    @property
    def Name(self) -> str:  # noqa: N802
        return self._name

    @Name.setter
    def Name(self, value: str) -> None:  # noqa: N802
        if self._part.refuse_rename:
            raise RuntimeError("rename refused")
        self._part.cuts[value] = self._part.cuts.pop(self._name)
        self._name = value

    def Select2(self, _append: bool, _mark: int) -> bool:  # noqa: N802
        self._part.selected = self
        return True


class _Part:
    """A part with one sketch and a given amount of material on each side.

    ``along`` and ``against`` are the mm³ a cut removes along and against the
    sketch normal; ``None`` means no material there, so SolidWorks builds no
    feature. As in SolidWorks, every cut takes the next number, even after a
    delete.
    """

    def __init__(self, along: float | None, against: float | None) -> None:
        # Keyed by FeatureCut4's Dir: True is along the sketch normal.
        self.material = {True: along, False: against}
        self.volume = _VOLUME
        self.cuts: dict[str, _Cut] = {}
        self.calls: list[tuple[str, bool]] = []
        self.deleted: list[str] = []
        self.selected: _Cut | None = None
        self.refuse_rename = False
        self.refuse_delete: set[int] = set()
        self.refuse_cut_from = 0
        self._number = 0
        self._deletes = 0
        sketch = SimpleNamespace(
            GetTypeName2=lambda: "ProfileFeature",
            Name="Sketch3",
            GetNextFeature=lambda: None,
        )
        self.FirstFeature = lambda: sketch
        self.FeatureManager = SimpleNamespace(
            FeatureCut4=lambda *args: self._cut("FeatureCut4", args),
            FeatureCut3=lambda *args: self._cut("FeatureCut3", args),
            GetFeatureCount=lambda _hidden: len(self.cuts) + 1,
        )
        self.Extension = SimpleNamespace(
            SelectByID2=lambda *_args: True, DeleteSelection2=self._delete
        )
        self.SelectionManager = SimpleNamespace(
            GetSelectedObjectCount2=lambda _mark: int(self.selected is not None)
        )

    def ClearSelection2(self, _all: bool) -> bool:  # noqa: N802
        self.selected = None
        return True

    def EditRebuild3(self) -> bool:  # noqa: N802
        return True

    def FeatureByName(self, name: str) -> _Cut | None:  # noqa: N802
        return self.cuts.get(name)

    def _cut(self, api: str, args: tuple[Any, ...]) -> _Cut | None:
        self.calls.append((api, args[2]))
        removed = self.material[args[2]]
        if removed is None or 0 < self.refuse_cut_from <= len(self.calls):
            return None
        self._number += 1
        cut = _Cut(self, f"Cut-Extrude{self._number}", removed)
        self.cuts[cut.Name] = cut
        self.volume -= removed
        return cut

    def _delete(self, _option: int) -> bool:
        self._deletes += 1
        cut = self.selected
        if cut is None or self._deletes in self.refuse_delete:
            return False
        del self.cuts[cut.Name]
        self.volume += cut.removed
        self.deleted.append(cut.Name)
        self.selected = None
        return True


class _Adapter:
    """Just enough adapter for the cut, the delete and the volume read."""

    def __init__(self, part: _Part | None, unreadable: tuple[int, ...] = ()) -> None:
        self.currentModel = part
        self.constants = {
            "swEndCondBlind": 1,
            "swEndCondThroughAll": 2,
            "swEndCondThroughAllBoth": 9,
            "swStartSketchPlane": 0,
        }
        self.swApp = SimpleNamespace(RevisionNumber="34.1.0")
        self._last_sketch_name = "Sketch3"
        self.unreadable = unreadable
        self.volume_reads = 0

    def _handle_com_operation(self, _name: str, callback: Any) -> AdapterResult[Any]:
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, callback: Any, default: Any = None) -> Any:
        try:
            return callback()
        except Exception:
            return default

    def _attempt_with_error(self, callback: Any) -> tuple[Any, Exception | None]:
        try:
            return callback(), None
        except Exception as exc:
            return None, exc

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value

    def _get_feature_id(self, feature: Any) -> str:
        return str(feature.Name)

    async def get_mass_properties(self) -> AdapterResult[Any]:
        self.volume_reads += 1
        if self.volume_reads in self.unreadable:
            return AdapterResult(status=AdapterResultStatus.ERROR, error="no mass")
        assert self.currentModel is not None
        volume = SimpleNamespace(volume=self.currentModel.volume)
        return AdapterResult(status=AdapterResultStatus.SUCCESS, data=volume)


async def _cut(part: _Part, *, unreadable: tuple[int, ...] = (), **fields: Any):
    adapter = _Adapter(part, unreadable)
    params = ExtrusionParameters(depth=fields.pop("depth", 2.0), **fields)
    result = await features._create_cut_extrude_choosing_side(adapter, params)
    return adapter, result


def _dirs(part: _Part) -> list[bool]:
    """The Dir of every FeatureCut call, in order (True: along the normal)."""
    return [dir_ for _api, dir_ in part.calls]


# ---- the bug: a cut on the plane a boss grew from ------------------------------


@pytest.mark.asyncio
async def test_the_boss_side_wins_over_a_sliver_on_the_other_side() -> None:
    """Along the normal (into the boss) 9.05 mm³; the other side 1.13 mm³."""
    part = _Part(along=9.05, against=1.13)

    _adapter, result = await _cut(part)

    assert result.is_success, result.error
    assert result.data.name == "Cut-Extrude1"
    assert list(part.cuts) == ["Cut-Extrude1"]
    assert part.volume == pytest.approx(_VOLUME - 9.05)
    parameters = result.data.parameters
    assert parameters["direction_flipped"] is False
    assert parameters["reverse_direction"] is True  # Dir=True: along the normal
    assert parameters["direction_choice"] == "more_material"
    assert parameters["volume_removed_mm3"] == pytest.approx(
        {"along_normal": 9.05, "against_normal": 1.13}
    )
    # Along, against, then along again; each FeatureCut4 builds.
    assert _dirs(part) == [True, False, True]


@pytest.mark.asyncio
async def test_a_sliver_along_the_normal_loses_to_the_other_side() -> None:
    part = _Part(along=1.13, against=9.05)

    _adapter, result = await _cut(part)

    assert result.is_success, result.error
    assert result.data.name == "Cut-Extrude1"
    assert part.volume == pytest.approx(_VOLUME - 9.05)
    parameters = result.data.parameters
    assert parameters["direction_flipped"] is True
    assert parameters["reverse_direction"] is False
    assert parameters["direction_choice"] == "more_material"
    assert _dirs(part) == [True, False]


@pytest.mark.asyncio
async def test_equal_sides_keep_the_sketch_normal() -> None:
    """A sketch through the middle of a block: both sides remove 37.70 mm³."""
    part = _Part(along=37.70, against=37.70 + 1e-9)

    _adapter, result = await _cut(part)

    assert result.is_success, result.error
    assert result.data.parameters["direction_flipped"] is False
    assert result.data.parameters["direction_choice"] == "equal_material"
    assert part.volume == pytest.approx(_VOLUME - 37.70)
    assert list(part.cuts) == ["Cut-Extrude1"]


@pytest.mark.asyncio
async def test_material_only_along_the_normal_is_cut_again_after_the_trial() -> None:
    """A Top Plane sketch under a block extruded up from Top."""
    part = _Part(along=142.55, against=None)

    _adapter, result = await _cut(part, depth=6.0)

    assert result.is_success, result.error
    assert result.data.name == "Cut-Extrude1"
    assert part.volume == pytest.approx(_VOLUME - 142.55)
    parameters = result.data.parameters
    assert parameters["direction_flipped"] is False
    assert parameters["direction_choice"] == "only_side_with_material"
    assert parameters["volume_removed_mm3"] == {
        "along_normal": pytest.approx(142.55),
        "against_normal": 0.0,
    }
    # The other side builds nothing with FeatureCut4 or FeatureCut3.
    assert _dirs(part) == [True, False, False, True]


@pytest.mark.asyncio
async def test_material_only_against_the_normal_needs_no_trial() -> None:
    """A sketch on a face: the normal points out of the part."""
    part = _Part(along=None, against=50.0)

    adapter, result = await _cut(part)

    assert result.is_success, result.error
    parameters = result.data.parameters
    assert parameters["direction_flipped"] is True
    assert parameters["direction_choice"] == "only_side_with_material"
    assert "volume_removed_mm3" not in parameters
    assert _dirs(part) == [True, True, False]
    assert part.deleted == []
    assert adapter.volume_reads == 1


@pytest.mark.asyncio
async def test_no_material_on_either_side_names_both() -> None:
    part = _Part(along=None, against=None)

    _adapter, result = await _cut(part)

    assert result.is_error
    error = result.error or ""
    assert "built no feature" in error
    assert "tried: along the sketch normal; against the sketch normal" in error


# ---- a direction the caller set ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [True, False])
async def test_a_requested_direction_goes_to_dir_unchanged(reverse: bool) -> None:
    """Even toward the sliver: no trial, no volume read."""
    part = _Part(along=1.13, against=9.05)

    adapter, result = await _cut(part, reverse_direction=reverse)

    assert result.is_success, result.error
    parameters = result.data.parameters
    assert parameters["reverse_direction"] is reverse
    assert parameters["direction_flipped"] is False
    assert parameters["direction_choice"] == "requested"
    assert _dirs(part) == [reverse]
    assert adapter.volume_reads == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reverse", "along", "against"), [(True, None, 9.05), (False, 9.05, None)]
)
async def test_a_requested_side_without_material_flips_once(
    reverse: bool, along: float | None, against: float | None
) -> None:
    """The old retry: the other side, reported as flipped."""
    part = _Part(along=along, against=against)

    adapter, result = await _cut(part, reverse_direction=reverse)

    assert result.is_success, result.error
    parameters = result.data.parameters
    assert parameters["reverse_direction"] is not reverse
    assert parameters["direction_flipped"] is True
    assert parameters["direction_choice"] == "flipped"
    assert _dirs(part) == [reverse, reverse, not reverse]
    assert adapter.volume_reads == 0


@pytest.mark.asyncio
async def test_a_requested_side_names_both_sides_when_neither_cuts() -> None:
    part = _Part(along=None, against=None)

    _adapter, result = await _cut(part, reverse_direction=False)

    assert result.is_error
    error = result.error or ""
    assert "tried: against the sketch normal; along the sketch normal" in error
    assert _dirs(part) == [False, False, True, True]
    assert part.cuts == {}


@pytest.mark.asyncio
async def test_through_all_both_ways_has_no_side_to_pick() -> None:
    part = _Part(along=5.0, against=5.0)

    adapter, result = await _cut(part, end_condition="ThroughAllBoth")

    assert result.is_success, result.error
    assert result.data.parameters["direction_choice"] == "both_directions"
    assert result.data.parameters["direction_flipped"] is False
    # Dir is passed as given (False) for a double-ended cut, as measured.
    assert _dirs(part) == [False]
    assert adapter.volume_reads == 0


@pytest.mark.asyncio
async def test_no_active_model_reads_nothing() -> None:
    adapter = _Adapter(None)

    result = await features._create_cut_extrude_choosing_side(
        adapter, ExtrusionParameters(depth=1.0)
    )

    assert result.error == "No active model"
    assert adapter.volume_reads == 0


# ---- when the sides can't be compared -------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("unreadable", [(1,), (2,)])
async def test_an_unreadable_volume_keeps_the_first_side_that_cut(
    unreadable: tuple[int, ...],
) -> None:
    part = _Part(along=1.13, against=9.05)

    _adapter, result = await _cut(part, unreadable=unreadable)

    assert result.is_success, result.error
    parameters = result.data.parameters
    assert parameters["direction_choice"] == "not_compared"
    assert parameters["direction_note"] == "the part's volume could not be read"
    assert parameters["direction_flipped"] is False
    assert _dirs(part) == [True]


@pytest.mark.asyncio
async def test_an_unreadable_volume_after_the_other_side_goes_back_along() -> None:
    part = _Part(along=1.13, against=9.05)

    _adapter, result = await _cut(part, unreadable=(3,))

    assert result.is_success, result.error
    parameters = result.data.parameters
    assert parameters["direction_choice"] == "not_compared"
    assert parameters["direction_flipped"] is False
    assert "volume_removed_mm3" not in parameters
    assert part.volume == pytest.approx(_VOLUME - 1.13)
    assert _dirs(part) == [True, False, True]


@pytest.mark.asyncio
async def test_a_first_cut_that_cannot_be_deleted_stays() -> None:
    part = _Part(along=1.13, against=9.05)
    part.refuse_delete = {1}

    _adapter, result = await _cut(part)

    assert result.is_success, result.error
    parameters = result.data.parameters
    assert parameters["direction_choice"] == "not_compared"
    assert "could not be deleted to try the other side" in parameters["direction_note"]
    assert list(part.cuts) == ["Cut-Extrude1"]
    assert _dirs(part) == [True]


@pytest.mark.asyncio
async def test_an_other_side_cut_that_cannot_be_deleted_stays() -> None:
    part = _Part(along=9.05, against=1.13)
    part.refuse_delete = {2}

    _adapter, result = await _cut(part)

    assert result.is_success, result.error
    parameters = result.data.parameters
    assert parameters["direction_choice"] == "not_compared"
    assert parameters["direction_flipped"] is True
    assert "could not be deleted to cut along it again" in parameters["direction_note"]
    assert parameters["volume_removed_mm3"] == pytest.approx(
        {"along_normal": 9.05, "against_normal": 1.13}
    )
    assert part.volume == pytest.approx(_VOLUME - 1.13)


@pytest.mark.asyncio
async def test_a_first_side_that_cannot_be_cut_again_is_an_error() -> None:
    part = _Part(along=9.05, against=1.13)
    part.refuse_cut_from = 3

    _adapter, result = await _cut(part)

    assert result.is_error
    error = result.error or ""
    assert "removed 9.05 mm3" in error
    assert "the part has no cut from 'Sketch3'" in error
    assert part.cuts == {}


# ---- the impl's own pieces --------------------------------------------------------


def test_a_cut_keeps_its_solidworks_name_when_the_rename_is_refused() -> None:
    part = _Part(along=4.0, against=None)
    part.refuse_rename = True

    result = features._create_cut_extrude_impl(
        _Adapter(part), ExtrusionParameters(depth=1.0), reverse=True, name="Keep"
    )

    assert result.is_success, result.error
    assert result.data.name == "Cut-Extrude1"


def test_a_cut_already_named_as_asked_is_not_renamed() -> None:
    part = _Part(along=4.0, against=None)
    part.refuse_rename = True

    result = features._create_cut_extrude_impl(
        _Adapter(part),
        ExtrusionParameters(depth=1.0),
        reverse=True,
        name="Cut-Extrude1",
    )

    assert result.data.name == "Cut-Extrude1"


def test_a_forced_side_is_never_flipped() -> None:
    """The comparison's trials cut one side only, whatever it holds."""
    part = _Part(along=None, against=9.0)

    result = features._create_cut_extrude_impl(
        _Adapter(part), ExtrusionParameters(depth=1.0), reverse=True
    )

    assert result.is_error
    assert _dirs(part) == [True, True]


def test_the_impl_alone_does_not_compare_the_sides() -> None:
    part = _Part(along=1.0, against=9.0)

    result = features._create_cut_extrude_impl(
        _Adapter(part), ExtrusionParameters(depth=1.0)
    )

    assert result.data.parameters["direction_choice"] == "not_compared"
    assert _dirs(part) == [True]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (ExtrusionParameters(depth=1.0), None),
        (ExtrusionParameters(depth=1.0, reverse_direction=False), False),
        (ExtrusionParameters(depth=1.0, reverse_direction=True), True),
        (SimpleNamespace(depth=1.0), None),
        (SimpleNamespace(depth=1.0, reverse_direction=None), None),
        (SimpleNamespace(depth=1.0, reverse_direction=1), True),
    ],
)
def test_requested_cut_direction(params: Any, expected: bool | None) -> None:
    assert features._requested_cut_direction(params) is expected


@pytest.mark.parametrize(
    ("end_condition", "both", "expected"),
    [
        ("Blind", False, (False, False)),
        (None, True, (False, False)),
        ("Through All", False, (True, False)),
        ("through_all", True, (True, True)),
        ("ThroughAllBoth", False, (False, True)),
    ],
)
def test_cut_end_condition(
    end_condition: str | None, both: bool, expected: tuple[bool, bool]
) -> None:
    params = SimpleNamespace(end_condition=end_condition, both_directions=both)

    assert features._cut_end_condition(params) == expected


@pytest.mark.parametrize(
    ("removed", "other", "expected"),
    [(9.05, 1.13, True), (1.13, 9.05, False), (37.7 + 1e-9, 37.7, False)],
)
def test_removes_more(removed: float, other: float, expected: bool) -> None:
    assert features._removes_more(removed, other) is expected


@pytest.mark.asyncio
async def test_the_adapter_method_picks_the_side(monkeypatch) -> None:
    monkeypatch.setattr(
        "solidworks_mcp.adapters.pywin32_adapter.PYWIN32_AVAILABLE", True
    )
    monkeypatch.setattr(
        "solidworks_mcp.adapters.pywin32_adapter.platform.system", lambda: "Windows"
    )
    monkeypatch.setattr(
        "solidworks_mcp.adapters.pywin32_adapter.pywintypes",
        SimpleNamespace(com_error=RuntimeError),
        raising=False,
    )
    monkeypatch.setattr(
        "solidworks_mcp.adapters.pywin32_adapter._ComSessionCoordinator",
        lambda _adapter: SimpleNamespace(),
        raising=False,
    )
    sentinel = AdapterResult(status=AdapterResultStatus.SUCCESS, data=None)
    seen: list[Any] = []

    async def _choosing(adapter: Any, params: Any) -> AdapterResult[Any]:
        seen.append((adapter, params))
        return sentinel

    monkeypatch.setattr(features, "_create_cut_extrude_choosing_side", _choosing)
    adapter = PyWin32Adapter({})
    params = ExtrusionParameters(depth=1.0)

    assert await adapter.create_cut_extrude(params) is sentinel
    assert seen == [(adapter, params)]
