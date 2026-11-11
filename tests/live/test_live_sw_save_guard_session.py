"""The assembly save guard and this session's own saved edits, on real SolidWorks.

From the Cellvis dish rack: the parts were the user's files. After this
session had saved one, each later assembly save still asked before
overwriting it, though its new changes were this session's.

Run it with::

    powershell -ExecutionPolicy Bypass -File tests\\scripts\\live_demo.ps1 `
        -Test tests/live/test_live_sw_save_guard_session.py

Collected only with ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` on Windows (see
``tests/live/conftest.py``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from solidworks_mcp.adapters.solidworks import saving
from tests.live.evidence import evidence
from tests.live.test_live_sw_keep_minimized import _assembly_with_modified_part, _block

CONFIRM = saving.CONFIRM_FLAG


async def _edit_part(adapter: Any, part: Path, assembly: Path, plane: str) -> None:
    assert (await adapter.activate_document(str(part))).is_success
    await _block(adapter, plane=plane, x=-40.0)
    assert (await adapter.activate_document(str(assembly))).is_success


async def test_a_users_part_this_session_saved_is_not_asked_about_again(
    live_adapter: Any, scratch: Any, tmp_path: Path
) -> None:
    part, assembly = await _assembly_with_modified_part(live_adapter, scratch, tmp_path)
    # The user's part: a file this session neither created nor saved.
    saving.session_paths(live_adapter).discard(saving.normalize(str(part)))
    saving.session_saves(live_adapter).pop(saving.normalize(str(part)), None)

    asked = await live_adapter.save_file(None)
    confirmed = await live_adapter.save_file(None, True)
    await _edit_part(live_adapter, part, assembly, "Front")
    before_again = part.stat().st_mtime
    again = await live_adapter.save_file(None)
    after_again = part.stat().st_mtime
    await _edit_part(live_adapter, part, assembly, "Right")
    os.utime(part, (1, 1))  # as if saved elsewhere since
    elsewhere = await live_adapter.save_file(None)

    evidence(
        "the user's part: asked, confirmed, edited again and saved without asking; "
        "then saved elsewhere, so asked again",
        {
            "asked": asked.error,
            "again": again.data,
            "after_another_save": elsewhere.error,
        },
    )
    assert asked.is_error and asked.data["confirm_with"] == CONFIRM
    assert confirmed.is_success, confirmed.error
    assert again.is_success, again.error
    assert after_again != before_again  # the part was written
    assert elsewhere.is_error and elsewhere.data["confirm_with"] == CONFIRM
