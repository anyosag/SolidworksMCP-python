"""DISPIDs learned from one dispatch are reused for the next of the same kind.

``_FlagAsMethod(name)`` costs one ``GetIDsOfNames`` round trip to SolidWorks
per name, and ``swApp.ActiveDoc`` hands back a fresh wrapper on every read, so
a part document cost 906 round trips each time it was flagged. The memo keeps
the DISPIDs the first object returned and fills later objects' method maps
directly, after checking two canary names on the new object.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters import sw_type_info


class _MapEntry:
    def __init__(self, dispid: int, names: tuple[str, ...]) -> None:
        self.dispid = dispid
        self.names = names


class _OleObj:
    """Stand-in for the PyIDispatch: answers GetIDsOfNames from a numbering."""

    def __init__(self, numbering: dict[str, int], calls: list[str]) -> None:
        self._numbering = numbering
        self._calls = calls

    def GetIDsOfNames(self, _lcid: int, name: str) -> int:  # noqa: N802
        self._calls.append(name)
        if name not in self._numbering:
            raise RuntimeError("Unknown name.")
        return self._numbering[name]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _OleObj) and other._numbering is self._numbering

    __hash__ = object.__hash__


class _Dispatch:
    """Stand-in for a CDispatch, flagging the way pywin32 does."""

    def __init__(self, numbering: dict[str, int], calls: list[str]) -> None:
        self._oleobj_ = _OleObj(numbering, calls)
        self._olerepr_ = SimpleNamespace(mapFuncs={})

    def _FlagAsMethod(self, name: str) -> None:  # noqa: N802
        dispid = self._oleobj_.GetIDsOfNames(0, name)
        self._olerepr_.mapFuncs[name] = _MapEntry(dispid, (name,))


_NUMBERING = {"GetTitle": 101, "GetPathName": 102, "GetType": 103, "ForceRebuild3": 104}


@pytest.fixture
def memo(monkeypatch):
    """A loaded type library with one interface, and an empty memo."""
    monkeypatch.setattr(sw_type_info, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(sw_type_info, "_wrapper_module", object())
    monkeypatch.setattr(
        sw_type_info,
        "_interface_methods",
        {"IFeature": frozenset(_NUMBERING) | {"NotOnThisObject"}},
    )
    monkeypatch.setattr(sw_type_info, "_flag_cache", {})
    monkeypatch.setattr(sw_type_info, "_dispid_memo", {})
    monkeypatch.setattr(sw_type_info, "_dispid_memo_unsafe", set())
    monkeypatch.setattr(
        sw_type_info, "build", SimpleNamespace(MapEntry=_MapEntry), raising=False
    )
    monkeypatch.delenv("SOLIDWORKS_MCP_DISPID_MEMO", raising=False)
    return sw_type_info


def test_the_second_object_costs_two_round_trips(memo) -> None:
    calls: list[str] = []
    first = _Dispatch(_NUMBERING, calls)
    assert memo.flag_methods(first, "IFeature") == 4
    assert len(calls) == 5  # every name, including the one that isn't there

    calls.clear()
    second = _Dispatch(_NUMBERING, calls)
    assert memo.flag_methods(second, "IFeature") == 4

    assert sorted(calls) == ["ForceRebuild3", "GetType"]  # the two canaries
    funcs = second._olerepr_.mapFuncs
    assert {name: entry.dispid for name, entry in funcs.items()} == _NUMBERING
    assert funcs["GetTitle"].names == ("GetTitle",)
    assert funcs["GetTitle"] is not first._olerepr_.mapFuncs["GetTitle"]


def test_a_different_numbering_disables_the_memo_for_that_kind(memo) -> None:
    memo.flag_methods(_Dispatch(_NUMBERING, []), "IFeature")
    renumbered = {name: dispid + 1000 for name, dispid in _NUMBERING.items()}
    calls: list[str] = []
    other = _Dispatch(renumbered, calls)

    memo.flag_methods(other, "IFeature")

    assert other._olerepr_.mapFuncs["GetTitle"].dispid == 1101
    assert ("IFeature", None) in memo._dispid_memo_unsafe
    assert ("IFeature", None) not in memo._dispid_memo
    # From now on every object of that kind is flagged name by name.
    calls.clear()
    memo.flag_methods(_Dispatch(_NUMBERING, calls), "IFeature")
    assert len(calls) == 5


def test_the_context_keeps_document_types_apart(memo, monkeypatch) -> None:
    monkeypatch.setattr(
        sw_type_info, "_interface_methods", {"IModelDoc2": frozenset(_NUMBERING)}
    )
    monkeypatch.setattr(
        sw_type_info, "DOC_TYPE_TO_INTERFACES", {1: ("IModelDoc2",), 2: ("IModelDoc2",)}
    )
    memo.flag_doc(_Dispatch(_NUMBERING, []), 1)
    calls: list[str] = []

    memo.flag_doc(_Dispatch(_NUMBERING, calls), 2)

    assert len(calls) == 4  # nothing learned from a part is used on an assembly
    assert set(memo._dispid_memo) == {("IModelDoc2", 1), ("IModelDoc2", 2)}


def test_a_document_interface_without_a_type_never_uses_the_memo(
    memo, monkeypatch
) -> None:
    """Live SW 2026: 19 names get different DISPIDs on parts and assemblies."""
    monkeypatch.setattr(
        sw_type_info, "_interface_methods", {"IModelDoc2": frozenset(_NUMBERING)}
    )
    memo.flag_methods(_Dispatch(_NUMBERING, []), "IModelDoc2")
    calls: list[str] = []

    memo.flag_methods(_Dispatch(_NUMBERING, calls), "IModelDoc2")

    assert len(calls) == 4
    assert memo._dispid_memo == {}


def test_a_shared_document_name_catches_a_mislabelled_document(
    memo, monkeypatch
) -> None:
    """The canaries include names two document interfaces declare."""
    monkeypatch.setattr(
        sw_type_info,
        "_interface_methods",
        {
            "IModelDoc2": frozenset(_NUMBERING),
            "IPartDoc": frozenset({"GetPathName"}),  # shared with IModelDoc2
        },
    )
    monkeypatch.setattr(sw_type_info, "DOC_TYPE_TO_INTERFACES", {1: ("IModelDoc2",)})
    memo.flag_doc(_Dispatch(_NUMBERING, []), 1)
    # An assembly flagged as a part: only the shared name is numbered apart.
    assembly_numbering = {**_NUMBERING, "GetPathName": 9102}
    calls: list[str] = []
    other = _Dispatch(assembly_numbering, calls)

    memo.flag_doc(other, 1)

    assert "GetPathName" in calls
    assert other._olerepr_.mapFuncs["GetPathName"].dispid == 9102
    assert ("IModelDoc2", 1) in memo._dispid_memo_unsafe


def test_the_switch_turns_the_memo_off(memo, monkeypatch) -> None:
    monkeypatch.setenv("SOLIDWORKS_MCP_DISPID_MEMO", "0")
    memo.flag_methods(_Dispatch(_NUMBERING, []), "IFeature")
    calls: list[str] = []

    memo.flag_methods(_Dispatch(_NUMBERING, calls), "IFeature")

    assert len(calls) == 5
    assert memo._dispid_memo == {}


def test_objects_without_a_method_map_flag_every_name(memo) -> None:
    class _Plain:
        def __init__(self) -> None:
            self.flagged: list[str] = []

        def _FlagAsMethod(self, name: str) -> None:  # noqa: N802
            self.flagged.append(name)

    first, second = _Plain(), _Plain()
    memo.flag_methods(first, "IFeature")
    memo.flag_methods(second, "IFeature")

    assert len(second.flagged) == 5
    assert memo._dispid_memo == {}


def test_a_canary_check_without_an_oleobj_fails_safe(memo) -> None:
    assert memo._memo_matches(SimpleNamespace(), {"GetTitle": 101}) is False


def test_a_canary_check_that_raises_fails_safe(memo) -> None:
    broken = SimpleNamespace(
        _oleobj_=SimpleNamespace(
            GetIDsOfNames=lambda *_a: (_ for _ in ()).throw(RuntimeError("gone"))
        )
    )

    assert memo._memo_matches(broken, {"GetTitle": 101}) is False


def test_names_shared_by_two_interfaces_are_flagged_once(memo, monkeypatch) -> None:
    monkeypatch.setattr(
        sw_type_info,
        "_interface_methods",
        {
            "IModelDoc2": frozenset({"GetTitle", "GetType"}),
            "IPartDoc": frozenset({"GetType", "GetPathName"}),
        },
    )
    calls: list[str] = []

    memo.flag_methods(_Dispatch(_NUMBERING, calls), "IModelDoc2", "IPartDoc")

    assert sorted(calls) == ["GetPathName", "GetTitle", "GetType"]


def test_invalidating_everything_clears_the_memo(memo) -> None:
    memo.flag_methods(_Dispatch(_NUMBERING, []), "IFeature")
    memo._dispid_memo_unsafe.add(("IView", None))

    memo.invalidate_flag_cache()

    assert memo._dispid_memo == {}
    assert memo._dispid_memo_unsafe == set()


class TestSameComObject:
    """Two wrappers of one COM object compare equal by their IUnknown."""

    def test_two_wrappers_of_one_object(self) -> None:
        a, b = _Dispatch(_NUMBERING, []), _Dispatch(_NUMBERING, [])

        assert sw_type_info.same_com_object(a, b) is True

    def test_wrappers_of_different_objects(self) -> None:
        a = _Dispatch(_NUMBERING, [])
        b = _Dispatch(dict(_NUMBERING), [])

        assert sw_type_info.same_com_object(a, b) is False

    def test_none_and_plain_objects(self) -> None:
        a = _Dispatch(_NUMBERING, [])

        assert sw_type_info.same_com_object(None, a) is False
        assert sw_type_info.same_com_object(a, None) is False
        assert sw_type_info.same_com_object(object(), a) is False
        plain = object()
        assert sw_type_info.same_com_object(plain, plain) is True

    def test_a_comparison_that_raises(self) -> None:
        class _Angry:
            def __eq__(self, _other: object) -> bool:
                raise RuntimeError("RPC server unavailable")

            __hash__ = object.__hash__

        a = SimpleNamespace(_oleobj_=_Angry())
        b = SimpleNamespace(_oleobj_=_Angry())

        assert sw_type_info.same_com_object(a, b) is False
