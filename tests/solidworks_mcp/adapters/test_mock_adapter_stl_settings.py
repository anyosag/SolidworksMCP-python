"""The mock exports STL with mesh settings as the real adapter reports them."""

from __future__ import annotations

from pathlib import Path

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.utils.stl_mesh import check_stl


async def test_the_mock_reports_the_settings_it_applied(tmp_path: Path) -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()
    path = str(tmp_path / "out.stl")

    result = await adapter.export_stl_with_settings(path, {"resolution": "fine"})

    assert result.is_success
    assert result.data == {
        "file_path": path,
        "units": "mm",
        "document_type": "part",
        "mesh": {"applied": ["resolution fine"], "restored": True},
    }


async def test_the_mock_refuses_what_the_real_adapter_refuses() -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()

    bad = await adapter.export_stl_with_settings("o.stl", {"units": "furlong"})
    no_model = await adapter.export_stl_with_settings("o.stl", {"units": "mm"})

    assert "Unknown STL units" in (bad.error or "")
    assert no_model.error == "No active model"


async def test_an_assembly_goes_into_one_file_in_the_given_units(
    tmp_path: Path,
) -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_assembly()
    path = str(tmp_path / "rack.stl")

    result = await adapter.export_stl_with_settings(path, {"units": "in"})

    assert result.data["units"] == "in"
    assert result.data["document_type"] == "assembly"
    assert result.data["mesh"]["applied"] == [
        "units in",
        "all components in one file",
    ]


async def test_the_mock_writes_a_closed_mesh(tmp_path: Path) -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_assembly()
    path = tmp_path / "out.stl"

    result = await adapter.export_file(str(path), "stl")

    assert result.data["mesh"] == {
        "applied": ["all components in one file"],
        "restored": True,
    }
    check = check_stl(path, result.data["units"])
    assert (check["triangles"], check["closed"]) == (4, True)
    assert check["volume_mm3"] == 166.667
