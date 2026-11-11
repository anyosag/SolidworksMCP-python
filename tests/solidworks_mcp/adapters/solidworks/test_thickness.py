"""Wall thickness by casting rays inward (``thickness``).

The fake part is a 10 x 10 x 2 mm plate (z 0..2 mm): one tessellation
triangle on its top face and one on its bottom face. The fake
``RayIntersections`` traces each ray to the opposite face, as SolidWorks
would, so the measured thickness is the plate's 2 mm.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import limits
from solidworks_mcp.adapters.solidworks import thickness as th
from solidworks_mcp.adapters.solidworks.documentation import (
    SolidWorksDocumentationMixin,
)

_T = 0.002  # plate thickness, metres


def _triangle(z: float, up: bool) -> tuple[list[float], list[float]]:
    corners = [0.001, 0.001, z, 0.009, 0.001, z, 0.005, 0.009, z]
    normal = [0.0, 0.0, 1.0 if up else -1.0] * 3
    return corners, normal


class _Face:
    def __init__(self, z: float, up: bool) -> None:
        self._tri, self._norm = _triangle(z, up)

    def GetTessTriangles(self, _no_conversion: bool) -> list[float]:  # noqa: N802
        return self._tri

    def GetTessNorms(self) -> list[float]:  # noqa: N802
        return self._norm


class _Extension:
    """Traces each ray from inside the plate to the face it leaves through."""

    def __init__(self, model: _Model, hits: bool = True) -> None:
        self._model, self._hits = model, hits
        self.args: tuple[Any, ...] = ()

    def RayIntersections(self, *args: Any) -> int:  # noqa: N802
        self.args = args
        starts = list(getattr(args[1], "value", args[1]))
        directions = list(getattr(args[2], "value", args[2]))
        hits: list[float] = []
        for ray in range(len(starts) // 3):
            x, y, z = starts[3 * ray : 3 * ray + 3]
            dz = directions[3 * ray + 2]
            exit_z = _T if dz > 0 else 0.0
            # The face it starts on (an entry, filtered out) and the exit.
            hits += [0, ray, 1 | 16, x, y, z, 0, 0, 0]
            hits += [0, ray, 1 | 32, x, y, exit_z, 0, 0, dz]
        self._model.hits = hits if self._hits else []
        return len(hits) // 9 if self._hits else 0


class _Model:
    def __init__(self, faces: list[_Face] | None = None, hits: bool = True) -> None:
        self.faces = [_Face(_T, True), _Face(0.0, False)] if faces is None else faces
        self.Extension = _Extension(self, hits)
        self.hits: list[float] = []

    def GetBodies2(self, _kind: int, _visible: bool) -> list[Any]:  # noqa: N802
        return [SimpleNamespace(GetFaces=lambda: self.faces)] if self.faces else []

    def GetRayIntersectionsPoints(self) -> list[float]:  # noqa: N802
        return self.hits

    def GetType(self) -> int:  # noqa: N802
        return 1


class _Harness(SolidWorksDocumentationMixin):
    def __init__(self, model: Any) -> None:
        self.currentModel = model
        self.swApp = None

    def _handle_com_operation(self, name: str, operation: Any, *args: Any) -> Any:
        try:
            return AdapterResult(
                status=AdapterResultStatus.SUCCESS, data=operation(*args)
            )
        except Exception as exc:  # noqa: BLE001 - mirror the real adapter
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, operation: Any, default: Any = None) -> Any:
        try:
            return operation()
        except Exception:  # noqa: BLE001
            return default

    def _get_attr_or_call(self, obj: Any, name: str) -> Any:
        value = getattr(obj, name)
        return value() if callable(value) else value


# ---- pure pieces ---------------------------------------------------------------


def test_a_triangle_gives_its_centroid_and_three_inner_points() -> None:
    corners, normals = _triangle(_T, True)

    samples = th.sample_points(corners, normals)

    assert len(samples) == 4
    assert samples[0][0] == pytest.approx([0.005, 0.0036667, _T], abs=1e-6)
    assert samples[1][0] == pytest.approx([0.003, 0.0023333, _T], abs=1e-6)
    assert all(normal == [0.0, 0.0, 1.0] for _, normal in samples)


def test_triangles_without_a_normal_or_complete_numbers_are_skipped() -> None:
    corners, _ = _triangle(0.0, True)

    assert th.sample_points(corners, [0.0] * 9) == []
    assert th.sample_points(corners[:8], [0.0, 0.0, 1.0] * 3) == []
    assert th.sample_points(None, None) == []


def test_samples_are_thinned_evenly() -> None:
    assert th.thin_out(list(range(10)), 20) == list(range(10))
    assert th.thin_out(list(range(10)), 5) == [0, 2, 4, 6, 8]


def test_rays_start_just_inside_and_point_inward() -> None:
    starts, directions = th.ray_arrays([([0.0, 0.0, _T], [0.0, 0.0, 1.0])])

    assert starts == pytest.approx([0.0, 0.0, _T - 1e-6])
    assert directions == [-0.0, -0.0, -1.0]


def test_the_first_exit_along_each_ray_is_its_thickness() -> None:
    samples = [([0, 0, _T], [0, 0, 1]), ([0, 0, 0], [0, 0, -1])]
    hits = [
        0, 0, 17, 0, 0, _T, 0, 0, 0,  # entry at its own face: ignored
        0, 0, 33, 0, 0, 0.0005, 0, 0, 0,  # an exit 1.5 mm in
        0, 0, 33, 0, 0, 0.0, 0, 0, 0,  # a later exit: not the nearest
        0, 1, 0, 0, 0, 0.0000005, 0, 0, 0,  # within the start offset: ignored
        0, 7, 33, 0, 0, 0, 0, 0, 0,  # no such ray
    ]  # fmt: skip

    found = th.exit_distances(hits, samples)

    assert found == {0: pytest.approx(0.0015)}


def test_the_summary_names_the_thinnest_and_the_thin_spots() -> None:
    samples = [([0.001 * i, 0, 0], [0, 0, 1]) for i in range(30)]
    distances = {i: 0.0001 * (i + 1) for i in range(30)}  # 0.1 .. 3.0 mm

    summary = th.summarize(samples, distances, min_wall_mm=2.5)

    assert summary["min_thickness_mm"] == 0.1
    assert summary["at_mm"] == [0.0, 0.0, 0.0]
    assert summary["below_minimum"] == 24
    assert len(summary["thin_spots"]) == 20
    assert summary["ok"] is False
    assert summary["measured"] == 30


def test_a_summary_of_nothing_measured_says_unknown() -> None:
    summary = th.summarize([([0, 0, 0], [0, 0, 1])], {}, 1.0)

    assert summary["min_thickness_mm"] is None
    assert summary["ok"] is None
    assert summary["measured"] == 0


# ---- the ray cast ------------------------------------------------------------


def test_a_two_millimetre_plate_measures_two_millimetres() -> None:
    harness = _Harness(_Model())

    reply = th.measure_wall_thickness(harness, min_wall_mm=0.8)

    assert reply["min_thickness_mm"] == pytest.approx(2.0, abs=1e-3)
    assert reply["ok"] is True
    assert (reply["samples"], reply["measured"]) == (8, 8)
    assert (reply["bodies"], reply["faces"]) == (1, 2)
    args = harness.currentModel.Extension.args
    assert args[3:] == (th.RAY_ENTRY_EXIT, 1e-8, 0.0, True)


def test_a_wall_under_the_minimum_is_listed() -> None:
    reply = th.measure_wall_thickness(_Harness(_Model()), min_wall_mm=3.0, max_rays=10)

    assert reply["ok"] is False
    assert reply["below_minimum"] == 8
    assert reply["thin_spots"][0]["thickness_mm"] == pytest.approx(2.0, abs=1e-3)


@pytest.mark.parametrize(
    ("model", "error", "fragment"),
    [
        (_Model(faces=[]), LookupError, "no solid body"),
        (_Model(faces=[SimpleNamespace()]), LookupError, "No face of the part"),
        (_Model(hits=False), RuntimeError, "found no hit for 8 rays"),
    ],
)
def test_a_part_that_cannot_be_measured_says_why(
    model: _Model, error: type[Exception], fragment: str
) -> None:
    with pytest.raises(error, match=None) as caught:
        th.measure_wall_thickness(_Harness(model), 1.0)
    assert fragment in str(caught.value)


async def test_the_adapter_method_needs_a_part() -> None:
    harness = _Harness(_Model())
    measured = await harness.check_wall_thickness(1.0)
    assert measured.is_success, measured.error

    drawing = _Model()
    drawing.GetType = lambda: 3  # type: ignore[method-assign]
    refused = await _Harness(drawing).check_wall_thickness()
    assert refused.error == (
        "check_wall_thickness needs an active part document (active document is "
        "drawing)."
    )


def test_sampling_stops_when_the_client_has_gone() -> None:
    limits.mark_client_gone("test")

    with pytest.raises(limits.OperationStopped, match="Stopped sampling faces"):
        th.measure_wall_thickness(_Harness(_Model()), 1.0)
