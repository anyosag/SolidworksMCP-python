"""The mock mirrors the window state and the save confirmation (keep-solidworks-minimized)."""

from __future__ import annotations

import pytest

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


@pytest.fixture
async def adapter() -> MockSolidWorksAdapter:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    return mock


async def test_set_window_state(adapter: MockSolidWorksAdapter) -> None:
    minimized = await adapter.set_window_state("minimize")
    restored = await adapter.set_window_state("restore")
    unknown = await adapter.set_window_state("maximize")

    assert minimized.data == {"window_state": "minimized"}
    assert restored.data == {"window_state": "normal"}
    assert unknown.is_error and "minimize or restore" in (unknown.error or "")


async def test_export_image_reports_the_window_state(
    adapter: MockSolidWorksAdapter, tmp_path
) -> None:
    await adapter.create_part()
    await adapter.set_window_state("minimize")

    result = await adapter.export_image({"file_path": str(tmp_path / "shot.png")})

    assert result.data["window_state"] == "minimized"


async def test_saving_an_assembly_over_the_users_files_needs_confirmation(
    adapter: MockSolidWorksAdapter,
) -> None:
    await adapter.create_assembly()
    adapter._modified_user_files = ["C:/work/rail.SLDPRT"]

    refused = await adapter.save_file()
    confirmed = await adapter.save_file(None, True)
    again = await adapter.save_file()

    assert refused.is_error
    assert refused.data == {
        "files": ["C:/work/rail.SLDPRT"],
        "confirm_with": "overwrite_modified_references",
    }
    assert confirmed.data["saved_references"] == ["C:/work/rail.SLDPRT"]
    assert again.is_success and again.data["saved_references"] == []


async def test_a_part_save_never_asks(adapter: MockSolidWorksAdapter) -> None:
    await adapter.create_part()
    adapter._modified_user_files = ["C:/work/rail.SLDPRT"]

    assert (await adapter.save_file()).is_success


async def test_close_with_save_needs_the_same_confirmation(
    adapter: MockSolidWorksAdapter,
) -> None:
    await adapter.create_assembly()
    adapter._modified_user_files = ["C:/work/rail.SLDPRT"]

    refused = await adapter.close_model(save=True)
    assert refused.is_error and refused.data["files"] == ["C:/work/rail.SLDPRT"]
    assert adapter._current_model is not None  # still open

    closed = await adapter.close_model(save=True, overwrite_modified_references=True)
    assert closed.is_success
    assert adapter._modified_user_files == []


async def test_close_without_save_never_asks(adapter: MockSolidWorksAdapter) -> None:
    await adapter.create_assembly()
    adapter._modified_user_files = ["C:/work/rail.SLDPRT"]

    assert (await adapter.close_model()).is_success
