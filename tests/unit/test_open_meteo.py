from __future__ import annotations

from datetime import UTC, datetime

from tests.fake_http import FakeHttp
from weorold import GeoPoint
from weorold.weather import OpenMeteoWeatherSource


def test_open_meteo_maps_model_fields_to_weather_samples():
    http = FakeHttp(
        {
            "https://example.test/forecast": {
                "elevation": 250.0,
                "generationtime_ms": 3.5,
                "hourly": {
                    "time": ["2026-08-14T12:00", "2026-08-14T13:00"],
                    "temperature_2m": [25.0, 26.0],
                    "relative_humidity_2m": [60.0, 55.0],
                    "precipitation": [0.0, 1.2],
                    "surface_pressure": [990.0, 989.0],
                    "cloud_cover": [20.0, 40.0],
                    "wind_speed_10m": [2.5, 3.0],
                    "wind_direction_10m": [350.0, 10.0],
                    "direct_normal_irradiance_instant": [700.0, 650.0],
                    "diffuse_radiation_instant": [80.0, 110.0],
                },
            }
        }
    )
    result = OpenMeteoWeatherSource(http, endpoint="https://example.test/forecast").fetch(
        GeoPoint(40.0, -75.0),
        start=datetime(2026, 8, 14, 12, tzinfo=UTC),
        end=datetime(2026, 8, 14, 13, tzinfo=UTC),
    )

    first = result.samples[0]
    assert first.air_temperature_c == 25.0
    assert first.wind_speed_m_s == 2.5
    assert first.direct_normal_irradiance_w_m2 == 700.0
    assert first.diffuse_horizontal_irradiance_w_m2 == 80.0
    assert first.pressure_pa == 99_000.0
    assert result.samples[1].precipitation_mm_h == 1.2


def test_open_meteo_uses_supplied_route_elevation_for_downscaling():
    http = FakeHttp(
        {
            "https://example.test/forecast": {
                "elevation": 515.0,
                "hourly": {
                    "time": ["2026-08-14T12:00", "2026-08-14T13:00"],
                    "temperature_2m": [20.0, 20.0],
                    "relative_humidity_2m": [50.0, 50.0],
                    "precipitation": [0.0, 0.0],
                    "surface_pressure": [950.0, 950.0],
                    "cloud_cover": [0.0, 0.0],
                    "wind_speed_10m": [1.0, 1.0],
                    "wind_direction_10m": [0.0, 0.0],
                    "direct_normal_irradiance_instant": [500.0, 500.0],
                    "diffuse_radiation_instant": [50.0, 50.0],
                },
            }
        }
    )
    OpenMeteoWeatherSource(http, endpoint="https://example.test/forecast").fetch(
        GeoPoint(40.0, -75.0),
        start=datetime(2026, 8, 14, 12, tzinfo=UTC),
        end=datetime(2026, 8, 14, 13, tzinfo=UTC),
        elevation_m=515.0,
    )
    _url, params = http.calls[0]
    assert isinstance(params, dict)
    assert params["elevation"] == 515.0
