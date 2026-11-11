"""The save guard tells this session's saved edits apart from the user's.

From the Cellvis dish rack: the parts were the user's own files. Once this
session had saved them, every later assembly save still asked before
overwriting them, though all their new changes were this session's.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from solidworks_mcp.adapters.solidworks import saving
from solidworks_mcp.adapters.solidworks.saving import NeedsConfirmation

from .test_saving import _Adapter, _assembly, _Doc, _file, _plain_dispatch  # noqa: F401


def test_a_part_this_session_saved_is_its_own_until_someone_else_saves_it(
    tmp_path: Path,
) -> None:
    adapter = _Adapter()
    part = _Doc(_file(tmp_path, "base.SLDPRT"), dirty=True)
    rack = _assembly(tmp_path, part)
    assert isinstance(saving.save_document(adapter, rack), NeedsConfirmation)

    saving.save_document(adapter, part)  # the user's part, saved by this session
    part.dirty = True  # this session edits it again
    again = saving.save_document(adapter, rack)

    assert not isinstance(again, NeedsConfirmation)
    assert again["saved_references"] == [part.path]
    # Saved by someone else since: it is the user's again.
    os.utime(part.path, (1, 1))
    part.dirty = True
    assert saving.save_document(adapter, rack) == NeedsConfirmation([part.path])


def test_the_parts_an_assembly_save_wrote_are_recorded(tmp_path: Path) -> None:
    adapter = _Adapter()
    part = _Doc(_file(tmp_path, "top.SLDPRT"), dirty=True)
    rack = _assembly(tmp_path, part)

    saving.save_document(adapter, rack, overwrite_modified_references=True)
    part.dirty = True

    assert saving.saved_by_session(adapter, part.path)
    assert not isinstance(saving.save_document(adapter, rack), NeedsConfirmation)


def test_a_file_gone_since_its_save_is_not_counted(tmp_path: Path) -> None:
    adapter = _Adapter()
    path = _file(tmp_path, "gone.SLDPRT")
    saving.record_save(adapter, path)
    os.remove(path)

    assert saving.saved_by_session(adapter, path) is False
    assert saving.saved_by_session(adapter, str(tmp_path / "never.SLDPRT")) is False


@pytest.mark.parametrize("missing", [True, False])
def test_a_save_record_without_a_time_never_counts(
    tmp_path: Path, missing: bool
) -> None:
    adapter = _Adapter()
    path = str(tmp_path / "x.SLDPRT")
    if not missing:
        Path(path).write_bytes(b"x")
    saving.session_saves(adapter)[saving.normalize(path)] = None

    assert saving.saved_by_session(adapter, path) is False
