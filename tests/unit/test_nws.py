from __future__ import annotations

from datetime import UTC, datetime

from tests.fake_http import FakeHttp
from weorold import GeoPoint
from weorold.weather import NwsWeatherSource


def test_nws_grid_data_is_normalized_and_solar_is_nonzero_in_daylight():
    point_url = "https://api.example/points/40.000000,-75.000000"
    grid_url = "https://api.example/gridpoints/PHI/1,2"

    def series(value, uom=None):
        return {
            "uom": uom,
            "values": [
                {
                    "validTime": "2026-08-14T12:00:00+00:00/PT2H",
                    "value": value,
                }
            ],
        }

    http = FakeHttp(
        {
            point_url: {
                "properties": {
                    "forecastGridData": grid_url,
                    "gridId": "PHI",
                    "gridX": 1,
                    "gridY": 2,
                }
            },
            grid_url: {
                "properties": {
                    "temperature": series(25.0, "wmoUnit:degC"),
                    "dewpoint": series(15.0, "wmoUnit:degC"),
                    "relativeHumidity": series(50.0, "wmoUnit:percent"),
                    "windSpeed": series(18.0, "wmoUnit:km_h-1"),
                    "windDirection": series(270.0, "wmoUnit:degree_(angle)"),
                    "skyCover": series(20.0, "wmoUnit:percent"),
                    "quantitativePrecipitation": series(4.0, "wmoUnit:mm"),
                }
            },
        }
    )

    result = NwsWeatherSource(
        http,
        api_root="https://api.example",
    ).fetch(
        GeoPoint(40.0, -75.0),
        start=datetime(2026, 8, 14, 12, tzinfo=UTC),
        end=datetime(2026, 8, 14, 13, tzinfo=UTC),
    )

    first = result.samples[0]

    assert first.wind_speed_m_s == 5.0
    assert first.precipitation_mm_h == 2.0
    assert first.wind_direction_deg == 270.0
    assert first.direct_normal_irradiance_w_m2 is None
    assert first.diffuse_horizontal_irradiance_w_m2 is None
    assert first.pressure_pa is None

    assert result.office == "PHI"
