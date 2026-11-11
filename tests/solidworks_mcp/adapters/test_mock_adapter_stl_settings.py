"""The mock exports STL with mesh settings as the real adapter reports them."""

from __future__ import annotations

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_the_mock_reports_the_settings_it_applied() -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()
    await adapter.create_part()

    result = await adapter.export_stl_with_settings("out.stl", {"resolution": "fine"})

    assert result.is_success
    assert result.data == {
        "file_path": "out.stl",
        "mesh": {"applied": ["resolution fine"], "restored": True},
    }


async def test_the_mock_refuses_what_the_real_adapter_refuses() -> None:
    adapter = MockSolidWorksAdapter({})
    await adapter.connect()

    bad = await adapter.export_stl_with_settings("o.stl", {"units": "furlong"})
    no_model = await adapter.export_stl_with_settings("o.stl", {"units": "mm"})

    assert "Unknown STL units" in (bad.error or "")
    assert no_model.error == "No active model"
