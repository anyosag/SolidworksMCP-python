"""Tests for silent saves and the overwrite confirmation (``saving.py``)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import io as io_mod
from solidworks_mcp.adapters.solidworks import saving
from solidworks_mcp.adapters.solidworks.saving import (
    SAVE_REFERENCED,
    SAVE_SILENT,
    NeedsConfirmation,
    Reference,
)


class _Doc:
    """An ``IModelDoc2`` with a path, a type and an unsaved-changes flag."""

    def __init__(self, path: str = "", doc_type: int = 1, dirty: bool = False) -> None:
        self.path = path
        self.doc_type = doc_type
        self.dirty = dirty
        self.components: list[Any] = []
        self.save3_calls: list[int] = []
        self.save_as3_calls: list[tuple[str, int]] = []
        self.save3_result: Any = True
        self.save3_errors = 0
        self.save3_warnings = 0
        self.save_as3_result: Any = 0

    def GetPathName(self) -> str:  # noqa: N802 - COM name
        return self.path

    def GetType(self) -> int:  # noqa: N802
        return self.doc_type

    def GetSaveFlag(self) -> bool:  # noqa: N802
        return self.dirty

    def GetComponents(self, top_level_only: bool) -> list[Any]:  # noqa: N802
        assert top_level_only is False  # every level
        return self.components

    def Save3(self, options: int, errors: Any, warnings: Any) -> Any:  # noqa: N802
        self.save3_calls.append(options)
        errors.value = self.save3_errors
        warnings.value = self.save3_warnings
        if self.save3_result and self.path:
            Path(self.path).write_bytes(b"saved")
            self.dirty = False
            for component in self.components:
                doc = component.doc
                if doc is not None and options & SAVE_REFERENCED:
                    doc.dirty = False
        return self.save3_result

    def SaveAs3(self, path: str, version: int, options: int) -> Any:  # noqa: N802
        self.save_as3_calls.append((path, options))
        if self.save_as3_result == 0:
            Path(path).write_bytes(b"saved as")
        return self.save_as3_result


class _Component:
    def __init__(self, doc: _Doc | None, virtual: bool = False) -> None:
        self.doc = doc
        self.IsVirtual = virtual

    def GetModelDoc2(self) -> _Doc | None:  # noqa: N802
        return self.doc


class _Adapter:
    """The adapter surface ``saving`` uses."""

    def __init__(self) -> None:
        self.swApp = SimpleNamespace(closed=[], CloseDoc=self._close)

    def _close(self, name: str) -> None:
        self.swApp.closed.append(name)

    def _attempt(self, fn: Any, default: Any = None) -> Any:
        try:
            return fn()
        except Exception:
            return default

    @staticmethod
    def _get_attr_or_call(obj: Any, name: str) -> Any:
        member = getattr(obj, name, None)
        return member() if callable(member) else member


@pytest.fixture(autouse=True)
def _plain_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_as_com`` wraps through ``dynamic.Dispatch``; fakes pass straight through."""
    monkeypatch.setattr(io_mod, "_dynamic", SimpleNamespace(Dispatch=lambda obj: obj))


@pytest.fixture
def adapter() -> _Adapter:
    return _Adapter()


def _file(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(b"the user's work")
    return str(path)


def _assembly(tmp_path: Path, *parts: _Doc, virtual: _Doc | None = None) -> _Doc:
    assembly = _Doc(_file(tmp_path, "rack.SLDASM"), doc_type=saving.DOC_ASSEMBLY)
    assembly.components = [_Component(p) for p in parts]
    if virtual is not None:
        assembly.components.append(_Component(virtual, virtual=True))
    assembly.components.append(_Component(None))  # suppressed: no model doc
    return assembly


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, []),
        (2 | 8192, ["swReadOnlySaveError", "swFileSaveRequiresSavingReferences"]),
        (SimpleNamespace(value=4), ["swFileNameEmpty"]),
        (None, []),
        ("not a number", []),
    ],
)
def test_flag_names(value: Any, expected: list[str]) -> None:
    assert saving.flag_names(value, saving.SAVE_ERRORS) == expected


def test_session_paths_are_per_adapter(adapter: _Adapter, tmp_path: Path) -> None:
    saving.remember(adapter, str(tmp_path / "A.SLDPRT"))

    assert saving.normalize(str(tmp_path / "A.SLDPRT")) in saving.session_paths(adapter)
    assert saving.session_paths(_Adapter()) == set()


def test_document_type(adapter: _Adapter) -> None:
    assert saving.document_type(adapter, _Doc(doc_type=2)) == 2
    assert saving.document_type(adapter, SimpleNamespace()) == 0
    assert saving.document_type(adapter, SimpleNamespace(GetType="x")) == 0


def test_modified_references_sorts_new_from_the_users(
    adapter: _Adapter, tmp_path: Path
) -> None:
    users = _Doc(_file(tmp_path, "rail.SLDPRT"), dirty=True)
    made_here = _Doc(_file(tmp_path, "bracket.SLDPRT"), dirty=True)
    saving.remember(adapter, made_here.path)
    unsaved = _Doc("", dirty=True)
    gone = _Doc(str(tmp_path / "deleted.SLDPRT"), dirty=True)
    clean = _Doc(_file(tmp_path, "clean.SLDPRT"), dirty=False)
    virtual = _Doc(_file(tmp_path, "virtual.SLDPRT"), dirty=True)
    assembly = _assembly(
        tmp_path, users, made_here, unsaved, gone, clean, users, virtual=virtual
    )

    references = saving.modified_references(adapter, assembly)

    assert references == [
        Reference(users.path, new=False),
        Reference(made_here.path, new=True),
        Reference("", new=True),
        Reference(gone.path, new=True),
        Reference(virtual.path, new=True),
    ]


def test_modified_references_of_an_unreadable_assembly(adapter: _Adapter) -> None:
    assert saving.modified_references(adapter, SimpleNamespace()) == []


def test_confirmation_result() -> None:
    result = saving.confirmation_result(["C:/a.SLDPRT"], 0.2)

    assert result.is_error
    assert result.error == (
        "Saving would overwrite 1 modified file that existed before this "
        "session: C:/a.SLDPRT. Nothing was saved."
    )
    assert result.data == {
        "files": ["C:/a.SLDPRT"],
        "confirm_with": "overwrite_modified_references",
    }
    assert "2 modified files" in saving.confirmation_message(["a", "b"])


def test_a_part_saves_silently_in_place(adapter: _Adapter, tmp_path: Path) -> None:
    part = _Doc(_file(tmp_path, "bracket.SLDPRT"))
    part.save3_warnings = 2

    outcome = saving.save_document(adapter, part)

    assert part.save3_calls == [SAVE_SILENT]
    assert outcome == {
        "file_path": part.path,
        "saved_references": [],
        "warnings": ["swFileSaveWarning_NeedsRebuild"],
    }


def test_a_refused_save_names_the_errors(adapter: _Adapter, tmp_path: Path) -> None:
    part = _Doc(_file(tmp_path, "bracket.SLDPRT"))
    part.save3_result = False
    part.save3_errors = 2

    with pytest.raises(Exception, match=r"Failed to save file \(swReadOnlySaveError\)"):
        saving.save_document(adapter, part)


def test_errors_fail_a_save_that_returned_true(
    adapter: _Adapter, tmp_path: Path
) -> None:
    part = _Doc(_file(tmp_path, "bracket.SLDPRT"))
    part.save3_errors = 16

    with pytest.raises(Exception, match="swFileLockError"):
        saving.save_document(adapter, part)


def test_an_assembly_saves_its_new_parts_with_it(
    adapter: _Adapter, tmp_path: Path
) -> None:
    bracket = _Doc(_file(tmp_path, "bracket.SLDPRT"), dirty=True)
    saving.remember(adapter, bracket.path)
    assembly = _assembly(tmp_path, bracket)

    outcome = saving.save_document(adapter, assembly)

    assert assembly.save3_calls == [SAVE_SILENT | SAVE_REFERENCED]
    assert isinstance(outcome, dict)
    assert outcome["saved_references"] == [bracket.path]


def test_overwriting_the_users_part_needs_confirmation(
    adapter: _Adapter, tmp_path: Path
) -> None:
    rail = _Doc(_file(tmp_path, "rail.SLDPRT"), dirty=True)
    assembly = _assembly(tmp_path, rail)
    before = Path(rail.path).read_bytes()

    outcome = saving.save_document(adapter, assembly)

    assert outcome == NeedsConfirmation([rail.path])
    assert assembly.save3_calls == []  # nothing written
    assert Path(rail.path).read_bytes() == before

    confirmed = saving.save_document(
        adapter, assembly, overwrite_modified_references=True
    )

    assert isinstance(confirmed, dict)
    assert confirmed["saved_references"] == [rail.path]
    assert assembly.save3_calls == [SAVE_SILENT | SAVE_REFERENCED]
    # Confirming once doesn't make the user's file the session's.
    assert saving.normalize(rail.path) not in saving.session_paths(adapter)


def test_save_as_a_new_path_is_remembered(adapter: _Adapter, tmp_path: Path) -> None:
    part = _Doc("")  # never saved
    target = tmp_path / "out" / "bracket.SLDPRT"

    outcome = saving.save_document(adapter, part, str(target))

    assert part.save_as3_calls == [(str(target), SAVE_SILENT)]
    assert adapter.swApp.closed == ["bracket.SLDPRT"]
    assert isinstance(outcome, dict) and outcome["file_path"] == str(target)
    assert saving.normalize(str(target)) in saving.session_paths(adapter)


def test_save_as_own_path_is_a_plain_save(adapter: _Adapter, tmp_path: Path) -> None:
    part = _Doc(_file(tmp_path, "bracket.SLDPRT"))

    saving.save_document(adapter, part, part.path.upper())

    assert part.save3_calls == [SAVE_SILENT]
    assert part.save_as3_calls == []
    assert saving.session_paths(adapter) == set()


@pytest.mark.parametrize(
    ("returned", "message"),
    [
        (128, r"Failed to save as: .* \(swFileSaveAsDoNotOverwrite\)"),
        (False, r"Failed to save as: [^(]*$"),
    ],
)
def test_a_refused_save_as(
    adapter: _Adapter, tmp_path: Path, returned: Any, message: str
) -> None:
    part = _Doc(_file(tmp_path, "bracket.SLDPRT"))
    part.save_as3_result = returned

    with pytest.raises(Exception, match=message):
        saving.save_document(adapter, part, str(tmp_path / "copy.SLDPRT"))


def test_save_as_without_solidworks_app(tmp_path: Path) -> None:
    adapter = _Adapter()
    adapter.swApp = None  # type: ignore[assignment]
    part = _Doc("")

    saving.save_document(adapter, part, str(tmp_path / "x.SLDPRT"))

    assert len(part.save_as3_calls) == 1


def test_a_never_saved_document_needs_a_path(adapter: _Adapter) -> None:
    with pytest.raises(Exception, match="never been saved"):
        saving.save_document(adapter, _Doc(""))


def test_a_save_that_writes_no_file(adapter: _Adapter, tmp_path: Path) -> None:
    part = _Doc(str(tmp_path / "missing.SLDPRT"))
    part.Save3 = lambda options, errors, warnings: True  # type: ignore[method-assign]

    with pytest.raises(Exception, match="File not written after save"):
        saving.save_document(adapter, part)


def test_confirmation_or_turns_needs_confirmation_into_an_error() -> None:
    needs = AdapterResult(
        status=AdapterResultStatus.SUCCESS,
        data=NeedsConfirmation(["C:/a.SLDPRT"]),
        execution_time=0.1,
    )
    plain = AdapterResult(status=AdapterResultStatus.SUCCESS, data={"file_path": "x"})

    converted = io_mod._confirmation_or(needs)

    assert converted.is_error and converted.data["files"] == ["C:/a.SLDPRT"]
    assert converted.execution_time == 0.1
    assert io_mod._confirmation_or(plain) is plain
