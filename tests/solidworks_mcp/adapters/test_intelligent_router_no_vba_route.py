"""Without a VBA route the router has nothing to choose, so it doesn't analyse."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.intelligent_router import IntelligentRouter
from solidworks_mcp.cache.response_cache import CachePolicy, ResponseCache


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [AdapterResultStatus.SUCCESS, AdapterResultStatus.ERROR]
)
async def test_no_vba_route_means_no_analysis(status) -> None:
    analyzer = Mock()
    router = IntelligentRouter(
        analyzer=analyzer, cache=ResponseCache(CachePolicy(enabled=False))
    )
    com = AsyncMock(return_value=AdapterResult(status=status, data={}))

    result, route = await router.execute(
        operation="create_extrusion",
        payload={"depth": 10},
        call_args=(),
        call_kwargs={},
        com_operation=com,
        vba_operation=None,
    )

    analyzer.analyze.assert_not_called()
    assert result.status == status
    assert route.route == (
        "com" if status == AdapterResultStatus.SUCCESS else "com-error"
    )
