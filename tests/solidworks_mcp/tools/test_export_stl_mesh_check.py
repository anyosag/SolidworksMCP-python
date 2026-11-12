"""``export_stl`` reads the file back: is the mesh closed, and how big is it?"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from fastmcp import FastMCP

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.tools.export import register_export_tools

# The mock writes a tetrahedron with 10 mm legs.
_TETRAHEDRON = {
    "triangles": 4,
    "closed": True,
    "open_edges": 0,
    "non_manifold_edges": 0,
    "volume_mm3": 166.667,
    "size_mm": [10.0, 10.0, 10.0],
    "units": "mm",
}


async def _export_stl(adapter: Any, config: Any) -> Any:
    mcp = FastMCP("stl")
    await register_export_tools(mcp, adapter, config)
    return next(t.fn for t in await mcp.list_tools() if t.name == "export_stl")


async def _mock(kind: str = "part") -> MockSolidWorksAdapter:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    if kind == "part":
        await adapter.create_part()
    else:
        await adapter.create_assembly()
    return adapter


def _ok(data: dict[str, Any]) -> AdapterResult[dict[str, Any]]:
    return AdapterResult(status=AdapterResultStatus.SUCCESS, data=data)


async def test_a_part_export_reports_the_mesh_it_wrote(
    mock_config: Any, tmp_path: Path
) -> None:
    export = await _export_stl(await _mock(), mock_config)

    result = await export({"file_path": str(tmp_path / "bracket.stl")})

    assert result["status"] == "success", result
    assert result["export"]["mesh_check"] == {
        **_TETRAHEDRON,
        "cad_volume_mm3": None,  # the mock has no geometry
        "volume_ratio": None,
    }
    assert "mesh" not in result["export"]


async def test_a_part_volume_is_compared_with_the_model(
    mock_config: Any, tmp_path: Path
) -> None:
    adapter = await _mock()
    adapter.get_model_geometry_summary = AsyncMock(  # type: ignore[method-assign]
        return_value=_ok({"document_type": "part", "volume_mm3": 170.0})
    )
    export = await _export_stl(adapter, mock_config)

    result = await export({"file_path": str(tmp_path / "bracket.stl")})

    check = result["export"]["mesh_check"]
    assert check["cad_volume_mm3"] == 170.0
    assert check["volume_ratio"] == 0.9804


async def test_an_assembly_says_it_went_into_one_file(
    mock_config: Any, tmp_path: Path
) -> None:
    adapter = await _mock("assembly")
    adapter.get_model_geometry_summary = AsyncMock()  # type: ignore[method-assign]
    export = await _export_stl(adapter, mock_config)

    result = await export({"file_path": str(tmp_path / "rack.stl")})

    assert result["export"]["mesh"] == {
        "applied": ["all components in one file"],
        "restored": True,
    }
    assert result["export"]["mesh_check"]["closed"] is True
    # An assembly's volume depends on the selection, so it isn't read.
    assert result["export"]["mesh_check"]["cad_volume_mm3"] is None
    adapter.get_model_geometry_summary.assert_not_awaited()
    assert "warning" not in result


async def test_the_units_given_convert_the_mesh_to_mm(
    mock_config: Any, tmp_path: Path
) -> None:
    export = await _export_stl(await _mock(), mock_config)

    result = await export({"file_path": str(tmp_path / "b.stl"), "units": "in"})

    check = result["export"]["mesh_check"]
    assert check["units"] == "in"
    assert check["size_mm"] == [254.0, 254.0, 254.0]
    assert result["export"]["mesh"]["applied"] == ["units in"]


class _Plain:
    """An adapter with only ``export_file``, writing nothing or a bad file."""

    def __init__(self, data: dict[str, Any], content: bytes | None = None) -> None:
        self.data = data
        self.content = content

    async def export_file(self, path: str, _fmt: str) -> AdapterResult[Any]:
        if self.content is not None:
            Path(path).write_bytes(self.content)
        return _ok(self.data)


async def test_a_file_that_cannot_be_read_does_not_fail_the_export(
    mock_config: Any, tmp_path: Path
) -> None:
    adapter = _Plain({"units": "mm", "document_type": "part"}, b"not an stl")
    export = await _export_stl(adapter, mock_config)

    result = await export({"file_path": str(tmp_path / "x.stl")})

    assert result["status"] == "success"
    assert list(result["export"]["mesh_check"]) == ["error"]
    assert "it is not an STL" in result["export"]["mesh_check"]["error"]


async def test_without_a_geometry_summary_the_model_volume_is_unknown(
    mock_config: Any, tmp_path: Path
) -> None:
    content = (await _mock_stl_bytes(tmp_path)).read_bytes()
    export = await _export_stl(_Plain({"document_type": "part"}, content), mock_config)

    result = await export({"file_path": str(tmp_path / "x.stl")})

    check = result["export"]["mesh_check"]
    assert check["closed"] is True
    assert check["units"] is None
    assert check["volume_ratio"] is None


async def _mock_stl_bytes(tmp_path: Path) -> Path:
    path = tmp_path / "mock.stl"
    await (await _mock()).export_file(str(path), "stl")
    return path


async def test_a_one_file_option_not_put_back_is_a_warning(
    mock_config: Any, tmp_path: Path
) -> None:
    adapter = _Plain(
        {"mesh": {"applied": ["all components in one file"], "restored": False}}
    )
    export = await _export_stl(adapter, mock_config)

    result = await export({"file_path": str(tmp_path / "rack.stl")})

    assert result["status"] == "success"
    assert "could not all be put back" in result["warning"]
    assert "error" in result["export"]["mesh_check"]  # nothing was written


async def test_an_adapter_with_its_own_stl_export_gets_the_check_too(
    mock_config: Any, tmp_path: Path
) -> None:
    class _Native:
        async def export_stl(self, _payload: dict[str, Any]) -> AdapterResult[Any]:
            return _ok({"triangle_count": 4})

    export = await _export_stl(_Native(), mock_config)

    result = await export({"file_path": str(tmp_path / "n.stl")})

    assert result["data"] == {"triangle_count": 4}
    assert result["export"]["format"] == "STL"
    assert "error" in result["export"]["mesh_check"]
