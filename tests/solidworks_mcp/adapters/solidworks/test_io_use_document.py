"""``use_document``: a document already active and this session's is not activated again."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks.io import SolidWorksIOMixin, document_names


class _Doc:
    def __init__(self, title: str, path: str = "") -> None:
        self.title, self.path = title, path

    def GetTitle(self) -> str:  # noqa: N802 - COM name
        return self.title

    def GetPathName(self) -> str:  # noqa: N802 - COM name
        return self.path


class _Harness(SolidWorksIOMixin):
    def __init__(self, active: Any, current: Any, last: Any) -> None:
        self.swApp = SimpleNamespace(ActiveDoc=active)
        self.currentModel = current
        self._last_active_document = last
        self.operations: list[str] = []
        self.activated: list[str] = []

    def is_connected(self) -> bool:
        return self.swApp is not None

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value

    @staticmethod
    def _document_key(doc: Any) -> tuple[str, str] | None:
        return None if doc is None else (doc.path.lower(), doc.title)

    def _handle_com_operation(self, name: str, callback: Any) -> AdapterResult[Any]:
        self.operations.append(name)
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    async def activate_document(self, title_or_path: str) -> AdapterResult[Any]:
        self.activated.append(title_or_path)
        if title_or_path == "Missing":
            return AdapterResult(
                status=AdapterResultStatus.ERROR,
                error="No open document matches 'Missing'. Open: Part7",
            )
        return AdapterResult(
            status=AdapterResultStatus.SUCCESS,
            data={"activated": title_or_path, "verified": True},
        )


PART7 = _Doc("Part7", "C:\\work\\Part7.SLDPRT")
KEY7 = ("c:\\work\\part7.sldprt", "Part7")


@pytest.mark.parametrize("name", ["Part7", "part7.sldprt", "C:\\work\\Part7.SLDPRT"])
async def test_the_active_document_of_this_session_is_not_activated_again(
    name: str,
) -> None:
    harness = _Harness(PART7, PART7, KEY7)

    result = await harness.use_document(name)

    assert result.is_success
    assert result.data == {"activated": "Part7", "verified": True, "switched": False}
    assert harness.operations == ["check_active_document"]
    assert harness.activated == []


@pytest.mark.parametrize(
    ("active", "current", "last"),
    [
        (_Doc("Part8"), PART7, KEY7),  # another document is active
        (PART7, _Doc("Part8"), KEY7),  # active, but the session works on another
        (PART7, PART7, ("", "Part8")),  # someone switched to it since the last call
        (None, PART7, KEY7),  # nothing active
    ],
)
async def test_otherwise_the_document_is_activated(
    active: Any, current: Any, last: Any
) -> None:
    harness = _Harness(active, current, last)

    result = await harness.use_document("Part7")

    assert result.is_success
    assert result.data["switched"] is True
    assert harness.activated == ["Part7"]


async def test_a_check_that_fails_falls_back_to_activating() -> None:
    harness = _Harness(SimpleNamespace(GetTitle=None), PART7, KEY7)

    result = await harness.use_document("Part7")

    assert harness.activated == ["Part7"]
    assert result.data["switched"] is True


async def test_a_document_that_is_not_open_is_an_error() -> None:
    harness = _Harness(PART7, PART7, KEY7)

    result = await harness.use_document("Missing")

    assert result.is_error
    assert "No open document matches 'Missing'" in (result.error or "")


async def test_without_solidworks_nothing_is_checked() -> None:
    harness = _Harness(PART7, PART7, KEY7)
    harness.swApp = None

    await harness.use_document("Part7")

    assert harness.operations == []
    assert harness.activated == ["Part7"]


def test_a_document_answers_to_its_title_path_and_file_name() -> None:
    assert document_names("Part7", "C:\\w\\Part7.SLDPRT") == {
        "part7",
        "c:\\w\\part7.sldprt",
        "part7.sldprt",
    }
    assert document_names(None, "") == set()
