"""``activate_doc``: activating a document shows no SolidWorks window.

Activating an assembly whose parts changed, live on SW 2026 SP4.1:
``ActivateDoc3`` option 0 asked "Would you like to rebuild the assembly
now?" in a box that took the foreground; option 2 showed a "Loading..."
dialog that took it too. Option 1 (don't rebuild) and then ``EditRebuild3``
showed nothing and left the assembly rebuilt (keep-solidworks-minimized,
design D4d). The user's rebuild preference is never touched.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.solidworks.io import activate_doc


class _Doc:
    def __init__(self, needs_rebuild: Any) -> None:
        self.rebuilds = 0
        if isinstance(needs_rebuild, Exception):
            error = needs_rebuild

            class _Extension:
                @property
                def NeedsRebuild2(self) -> int:  # noqa: N802
                    raise error

            self.Extension = _Extension()
        else:
            self.Extension = SimpleNamespace(NeedsRebuild2=needs_rebuild)

    def EditRebuild3(self) -> bool:  # noqa: N802
        self.rebuilds += 1
        return True


class _App:
    def __init__(self, doc: Any = None, activate_fails: bool = False) -> None:
        self.doc = doc
        self.activate_fails = activate_fails
        self.calls: list[tuple[str, bool, int]] = []

    def ActivateDoc3(  # noqa: N802
        self, title: str, use_user_preferences: bool, option: int, errors: Any
    ) -> Any:
        self.calls.append((title, use_user_preferences, option))
        if self.activate_fails:
            raise RuntimeError("no such document")
        return self.doc

    def __getattr__(self, name: str) -> Any:
        # Any other call (a preference read or write) is a test failure.
        raise AssertionError(f"activate_doc touched {name}")


class _Adapter:
    def _attempt(self, fn: Any, default: Any = None) -> Any:
        try:
            return fn()
        except AssertionError:
            raise
        except Exception:
            return default

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        attr = getattr(obj, name, None)
        return attr() if callable(attr) else attr


def test_activates_without_rebuilding_then_rebuilds_what_changed() -> None:
    doc = _Doc(needs_rebuild=1)  # swModelRebuildStatus_NonFrozenFeatureNeedsRebuild
    app = _App(doc)

    assert activate_doc(_Adapter(), app, "Rack.SLDASM") is doc

    # UseUserPreferences false, Option swDontRebuildActiveDoc: no window.
    assert app.calls == [("Rack.SLDASM", False, 1)]
    assert doc.rebuilds == 1


def test_an_up_to_date_document_is_not_rebuilt() -> None:
    doc = _Doc(needs_rebuild=0)

    activate_doc(_Adapter(), _App(doc), "Rail.SLDPRT")

    assert doc.rebuilds == 0


@pytest.mark.parametrize("unreadable", [None, RuntimeError("member not found")])
def test_an_unknown_rebuild_status_rebuilds(unreadable: Any) -> None:
    doc = _Doc(needs_rebuild=unreadable)

    activate_doc(_Adapter(), _App(doc), "Rack.SLDASM")

    assert doc.rebuilds == 1


def test_a_failed_activation_rebuilds_nothing_and_returns_none() -> None:
    app = _App(activate_fails=True)

    assert activate_doc(_Adapter(), app, "Missing.SLDASM") is None


def test_a_failed_rebuild_still_returns_the_document() -> None:
    doc = _Doc(needs_rebuild=1)

    def broken() -> bool:
        raise RuntimeError("rebuild failed")

    doc.EditRebuild3 = broken  # type: ignore[method-assign]

    assert activate_doc(_Adapter(), _App(doc), "Rack.SLDASM") is doc
