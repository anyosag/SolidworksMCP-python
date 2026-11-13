"""``check_printability`` for an adapter: export the part's mesh, then check it.

The part is exported to a temporary STL through the adapter's own
``export_stl_with_settings`` (fine resolution, mm, binary, in the model's
coordinates, so the points reported are the model's; the user's STL options are
put back), read, and checked by :func:`solidworks_mcp.utils.printability.analyse`.
The file is deleted afterwards. Change ``cellvis-assembly-and-print-checks``,
design D4.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Sequence
from typing import Any, cast

from ...utils import printability
from ...utils.stl_mesh import read_triangles
from ..base import AdapterResult, AdapterResultStatus

#: The STL settings of the mesh the check reads.
MESH_SETTINGS: dict[str, Any] = {
    "resolution": "fine",
    "units": "mm",
    "binary": True,
    "translate_to_positive": False,
}


async def check_part(
    adapter: Any,
    build_direction: str | Sequence[float],
    support_angle_deg: float = 45.0,
    min_bridge_mm: float = 5.0,
) -> AdapterResult[dict[str, Any]]:
    """Check the active part (the caller checked it is one) for printing.

    Args:
        adapter: An adapter with ``export_stl_with_settings``.
        build_direction: The direction the part grows from the plate.
        support_angle_deg: Down-facing surfaces under this angle need support.
        min_bridge_mm: Only longer bridges are listed.

    Returns:
        AdapterResult[dict[str, Any]]: The check (``analyse``), plus ``mesh``
        (the STL settings applied, and whether the user's came back).
    """
    try:
        printability.direction_vector(build_direction)
    except ValueError as exc:
        return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))
    folder = tempfile.mkdtemp(prefix="sw_print_check_")
    path = os.path.join(folder, "part.stl")
    try:
        exported = await adapter.export_stl_with_settings(path, dict(MESH_SETTINGS))
        if not exported.is_success:
            return cast(AdapterResult[dict[str, Any]], exported)
        try:
            data = printability.analyse(
                read_triangles(path, "mm"),
                build_direction,
                support_angle_deg,
                min_bridge_mm,
            )
        except (OSError, ValueError) as exc:
            return AdapterResult(
                status=AdapterResultStatus.ERROR,
                error=f"The part's mesh could not be checked: {exc}",
            )
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    exported_data = exported.data if isinstance(exported.data, dict) else {}
    data["mesh"] = exported_data.get("mesh")
    return AdapterResult(
        status=AdapterResultStatus.SUCCESS,
        data=data,
        execution_time=exported.execution_time,
    )
