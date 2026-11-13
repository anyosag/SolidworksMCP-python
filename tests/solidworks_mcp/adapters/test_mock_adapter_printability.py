"""The mock's print check: the real analysis on the mock's tetrahedron STL."""

from __future__ import annotations

from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter


async def test_a_part_is_checked() -> None:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_part()

    result = await mock.check_printability("z")

    assert result.is_success, result.error
    assert result.data["triangles"] == 4
    assert set(result.data) >= {
        "down_facing",
        "islands",
        "bridges",
        "suction_cups",
        "ok",
    }


async def test_an_assembly_is_refused() -> None:
    mock = MockSolidWorksAdapter({})
    await mock.connect()
    await mock.create_assembly()

    result = await mock.check_printability("z")

    assert result.error == "check_printability requires an active part document."
