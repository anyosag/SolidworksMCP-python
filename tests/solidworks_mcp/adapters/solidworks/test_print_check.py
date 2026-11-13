"""``check_printability`` for an adapter: export, read, check (``print_check``)."""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import print_check

# A 40 x 20 x 10 block's faces, each corner list counter-clockwise from outside.
_FACES = (
    ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)),
    ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
    ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)),
    ((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)),
    ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
    ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)),
)


def _block_stl(path: str) -> None:
    size = (40.0, 20.0, 10.0)

    def corner(c: tuple[int, int, int]) -> tuple[float, ...]:
        return tuple(size[i] * c[i] for i in range(3))

    triangles = []
    for p0, p1, p2, p3 in _FACES:
        triangles.append((*corner(p0), *corner(p1), *corner(p2)))
        triangles.append((*corner(p0), *corner(p2), *corner(p3)))
    data = b"block".ljust(80, b" ") + struct.pack("<I", len(triangles))
    for t in triangles:
        data += struct.pack("<12fH", 0.0, 0.0, 0.0, *t, 0)
    Path(path).write_bytes(data)


class _Adapter:
    """An adapter whose STL export writes ``write(path)``, or fails."""

    def __init__(self, write: Any = _block_stl, fails: bool = False) -> None:
        self._write, self._fails = write, fails
        self.exports: list[tuple[str, dict[str, Any]]] = []

    async def export_stl_with_settings(
        self, file_path: str, settings: dict[str, Any]
    ) -> AdapterResult[dict[str, Any]]:
        self.exports.append((file_path, settings))
        if self._fails:
            return AdapterResult(status=AdapterResultStatus.ERROR, error="no body")
        self._write(file_path)
        return AdapterResult(
            status=AdapterResultStatus.SUCCESS,
            data={"mesh": {"applied": ["resolution fine"], "restored": True}},
            execution_time=0.5,
        )


async def test_the_part_is_exported_in_model_coordinates_checked_and_deleted() -> None:
    adapter = _Adapter()

    result = await print_check.check_part(adapter, "z")

    assert result.is_success, result.error
    assert result.data["ok"] is True
    assert result.data["mesh"] == {"applied": ["resolution fine"], "restored": True}
    assert result.execution_time == 0.5
    ((path, settings),) = adapter.exports
    assert settings == print_check.MESH_SETTINGS
    assert settings["translate_to_positive"] is False
    assert not os.path.exists(os.path.dirname(path))


async def test_a_failed_export_is_the_reply() -> None:
    result = await print_check.check_part(_Adapter(fails=True), "z")

    assert result.error == "no body"


async def test_a_bad_direction_is_refused_before_the_export() -> None:
    adapter = _Adapter()

    result = await print_check.check_part(adapter, "sideways")

    assert "build_direction must be" in (result.error or "")
    assert adapter.exports == []


@pytest.mark.parametrize(
    "write",
    [lambda path: Path(path).write_bytes(b"not a mesh"), lambda path: None],
    ids=["not an STL", "no file"],
)
async def test_a_mesh_that_cannot_be_read_is_an_error(write: Any) -> None:
    result = await print_check.check_part(_Adapter(write=write), "z")

    assert (result.error or "").startswith("The part's mesh could not be checked:")
