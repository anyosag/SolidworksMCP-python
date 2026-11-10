"""Fewer COM round trips per call (docs/agents/mcp-speed-review.md).

* ``ActiveDoc`` hands back a fresh wrapper on every read. When it wraps the
  document ``currentModel`` already holds, the flagged ``currentModel`` is
  kept instead of being replaced and flagged again (906 round trips a part).
* ``list_features`` walks the tree a second time only when the first walk
  came up short of ``GetFeatureCount``.
* ``get_mass_properties`` rebuilds what is out of date, not every feature.
* ``is_application_running`` attaches without launching SolidWorks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from solidworks_mcp.adapters import pywin32_adapter
from solidworks_mcp.adapters.pywin32_adapter import PyWin32Adapter


@pytest.fixture
def adapter(monkeypatch) -> PyWin32Adapter:
    """A ``PyWin32Adapter`` that thinks it runs on Windows with pywin32."""
    monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(pywin32_adapter.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        pywin32_adapter,
        "pywintypes",
        SimpleNamespace(com_error=RuntimeError),
        raising=False,
    )
    monkeypatch.setattr(
        pywin32_adapter,
        "pythoncom",
        SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None),
        raising=False,
    )
    return PyWin32Adapter({})


class _Identity:
    """A COM identity: wrappers holding the same one wrap the same object."""


class _Doc:
    """A document wrapper; two wrappers share ``_oleobj_`` for one document."""

    def __init__(self, identity: _Identity, title: str = "Part1") -> None:
        self._oleobj_ = identity
        self._title = title
        self.FeatureManager = SimpleNamespace(GetFeatureCount=lambda _top: 0)

    def GetType(self) -> int:  # noqa: N802
        return 1

    def GetTitle(self) -> str:  # noqa: N802
        return self._title

    def FirstFeature(self) -> None:  # noqa: N802
        return None


class _App:
    """``swApp`` whose ``ActiveDoc`` is a new wrapper on every read."""

    def __init__(self, identity: _Identity | None) -> None:
        self.identity = identity

    @property
    def ActiveDoc(self) -> _Doc | None:  # noqa: N802
        return None if self.identity is None else _Doc(self.identity)


class TestTheFlaggedDocumentIsKept:
    def test_sync_keeps_current_model_for_the_same_document(self, adapter) -> None:
        identity = _Identity()
        flagged = _Doc(identity)
        adapter.currentModel = flagged
        adapter.swApp = _App(identity)

        assert adapter._sync_current_model_from_active() is flagged
        assert adapter.currentModel is flagged

    def test_sync_switches_to_another_document(self, adapter, monkeypatch) -> None:
        flagged_docs: list[object] = []
        monkeypatch.setattr(
            pywin32_adapter.sw_type_info,
            "flag_doc",
            lambda doc, _type: flagged_docs.append(doc),
        )
        adapter.currentModel = _Doc(_Identity())
        adapter.swApp = _App(_Identity())

        active = adapter._sync_current_model_from_active()

        assert active is adapter.currentModel
        assert flagged_docs == [active]

    @pytest.mark.asyncio
    async def test_list_features_keeps_current_model(self, adapter) -> None:
        identity = _Identity()
        flagged = _Doc(identity)
        adapter.currentModel = flagged
        adapter.swApp = _App(identity)

        result = await adapter.list_features()

        assert result.is_success
        assert adapter.currentModel is flagged

    @pytest.mark.asyncio
    async def test_list_features_follows_a_switch(self, adapter) -> None:
        adapter.currentModel = _Doc(_Identity())
        app = _App(_Identity())
        adapter.swApp = app

        await adapter.list_features()

        assert adapter.currentModel._oleobj_ is app.identity

    @pytest.mark.asyncio
    async def test_get_selected_entities_keeps_current_model(self, adapter) -> None:
        identity = _Identity()
        flagged = _Doc(identity)
        flagged.SelectionManager = SimpleNamespace(
            GetSelectedObjectCount2=lambda _mark: 0, _FlagAsMethod=lambda _n: None
        )
        adapter.currentModel = flagged
        adapter.swApp = _App(identity)

        result = await adapter.get_selected_entities()

        assert result.is_success
        assert adapter.currentModel is flagged


class _Feature:
    def __init__(self, name: str, nxt: _Feature | None = None) -> None:
        self.Name = name
        self._next = nxt

    def GetTypeName2(self) -> str:  # noqa: N802
        return "Boss"

    def IsSuppressed(self) -> bool:  # noqa: N802
        return False

    def GetNextFeature(self) -> _Feature | None:  # noqa: N802
        return self._next


@pytest.mark.asyncio
@pytest.mark.parametrize(("count", "reverse_reads"), [(2, 0), (3, 3)])
async def test_the_reverse_walk_runs_only_when_the_forward_walk_came_up_short(
    adapter, count, reverse_reads
) -> None:
    reverse = Mock(return_value=None)
    adapter.currentModel = SimpleNamespace(
        FirstFeature=lambda: _Feature("Sketch1", _Feature("Boss-Extrude1")),
        FeatureByPositionReverse=reverse,
        FeatureManager=SimpleNamespace(GetFeatureCount=lambda _top: count),
    )

    result = await adapter.list_features()

    assert [row["name"] for row in result.data] == ["Sketch1", "Boss-Extrude1"]
    assert reverse.call_count == reverse_reads


@pytest.mark.asyncio
async def test_mass_properties_rebuild_only_what_is_out_of_date(adapter) -> None:
    model = SimpleNamespace(
        EditRebuild3=Mock(return_value=True),
        ForceRebuild3=Mock(return_value=True),
        Extension=SimpleNamespace(CreateMassProperty=lambda: None),
        GetMassProperties=[0.0, 0.0, 0.0, 1e-6, 1e-4, 0.5],
    )
    adapter.currentModel = model

    result = await adapter.get_mass_properties()

    assert result.is_success
    model.EditRebuild3.assert_called_once_with()
    model.ForceRebuild3.assert_not_called()


class TestIsApplicationRunning:
    def test_a_running_instance(self, adapter, monkeypatch) -> None:
        monkeypatch.setattr(
            pywin32_adapter,
            "win32com",
            SimpleNamespace(
                client=SimpleNamespace(GetActiveObject=lambda _id: object())
            ),
        )

        assert adapter.is_application_running() is True
        assert adapter._com_initialized is True

    def test_nothing_running(self, adapter, monkeypatch) -> None:
        def _missing(_id: str) -> object:
            raise RuntimeError("Operation unavailable")

        monkeypatch.setattr(
            pywin32_adapter,
            "win32com",
            SimpleNamespace(client=SimpleNamespace(GetActiveObject=_missing)),
        )

        assert adapter.is_application_running() is False

    def test_without_pywin32(self, adapter, monkeypatch) -> None:
        monkeypatch.setattr(pywin32_adapter, "PYWIN32_AVAILABLE", False)

        assert adapter.is_application_running() is False


def test_an_unreadable_document_type_is_flagged_without_the_memo(
    adapter, monkeypatch
) -> None:
    """A document of unknown type gets the part interfaces, name by name."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        pywin32_adapter.sw_type_info,
        "flag_methods",
        lambda doc, *interfaces, **kwargs: calls.append((interfaces, kwargs)),
    )

    class _Unknown(_Doc):
        GetType = None  # unreadable

    app = _App(_Identity())
    app_doc = _Unknown(app.identity)
    adapter.swApp = SimpleNamespace(ActiveDoc=app_doc)
    adapter.currentModel = None

    assert adapter._sync_current_model_from_active() is app_doc
    assert calls == [(("IModelDoc2", "IPartDoc"), {})]
