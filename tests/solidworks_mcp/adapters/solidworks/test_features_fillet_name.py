"""A fillet reported as "Fillet" gets the name the tree shows.

``IModelDoc2.FeatureFillet3`` on SolidWorks 2025+ returns a number, not the
feature, so ``add_fillet`` answered "Fillet" and ``edit_feature`` then found no
such feature (first live run, 2026-11-11: the tree said "Fillet1").
"""

from __future__ import annotations

from typing import Any

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    SolidWorksFeature,
)
from solidworks_mcp.adapters.solidworks import features


def _tree(*names: str) -> AdapterResult[list[dict[str, Any]]]:
    return AdapterResult(
        status=AdapterResultStatus.SUCCESS, data=[{"name": n} for n in names]
    )


_FAILED = AdapterResult(status=AdapterResultStatus.ERROR, error="no part")


def _fillet(name: str = "Fillet") -> SolidWorksFeature:
    return SolidWorksFeature(name=name, type="Fillet", parameters={}, properties={})


def test_the_one_new_feature_names_the_fillet() -> None:
    fillet = _fillet()

    features._name_from_tree(
        fillet,
        _tree("Boss-Extrude1", "Sketch1"),
        _tree("Fillet1", "Boss-Extrude1", "Sketch1"),
    )

    assert fillet.name == "Fillet1"


@pytest.mark.parametrize(
    ("name", "before", "after"),
    [
        ("Fillet7", _tree("Boss-Extrude1"), _tree("Fillet1", "Boss-Extrude1")),
        ("Fillet", _FAILED, _tree("Fillet1")),
        ("Fillet", _tree("Boss-Extrude1"), _FAILED),
        (
            "Fillet",
            _tree("Boss-Extrude1"),
            _tree("Fillet1", "Fillet2", "Boss-Extrude1"),
        ),
    ],
)
def test_otherwise_the_name_stays(
    name: str, before: AdapterResult[Any], after: AdapterResult[Any]
) -> None:
    fillet = _fillet(name)

    features._name_from_tree(fillet, before, after)

    assert fillet.name == name
