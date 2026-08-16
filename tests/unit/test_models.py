from __future__ import annotations

from typing import Any

import pytest

from weorold import GeoPoint


def test_geo_point_canonicalizes_integer_coordinates_to_float() -> None:
    point = GeoPoint(40, -75)

    assert point.latitude_deg == 40.0
    assert point.longitude_deg == -75.0
    assert isinstance(point.latitude_deg, float)
    assert isinstance(point.longitude_deg, float)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (True, -75.0),
        (40.0, False),
        ("40", -75.0),
        (40.0, "-75"),
    ],
)
def test_geo_point_rejects_non_numeric_coordinates(
    latitude: Any,
    longitude: Any,
) -> None:
    with pytest.raises(TypeError):
        GeoPoint(latitude, longitude)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (91.0, 0.0),
        (-91.0, 0.0),
        (0.0, 181.0),
        (0.0, -181.0),
    ],
)
def test_geo_point_rejects_out_of_range_coordinates(
    latitude: float,
    longitude: float,
) -> None:
    with pytest.raises(ValueError):
        GeoPoint(latitude, longitude)
