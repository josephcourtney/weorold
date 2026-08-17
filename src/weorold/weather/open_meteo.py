from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from weorold.transport import HttpGetter
from weorold._validation import validate_time_window
from weorold.errors import DataSourceError
from weorold.models import GeoPoint
from weorold.weather.models import WeatherSample

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_HOURLY_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "surface_pressure",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "direct_normal_irradiance_instant",
    "diffuse_radiation_instant",
)


@dataclass(frozen=True, slots=True)
class OpenMeteoWeatherResult:
    samples: tuple[WeatherSample, ...]
    model: str | None
    model_elevation_m: float | None
    generation_time_ms: float | None


def _parse_utc_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        return datetime.fromisoformat(text[:-1] + "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataSourceError(f"Open-Meteo field {field!r} contains a non-numeric value")
    return float(value)


def _optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _validate_elevation(elevation_m: float | None) -> None:
    if elevation_m is None:
        return
    if isinstance(elevation_m, bool) or not isinstance(elevation_m, (int, float)):
        raise ValueError("elevation_m must be finite and numeric when supplied")
    if not isfinite(float(elevation_m)):
        raise ValueError("elevation_m must be finite and numeric when supplied")


def _request_params(
    location: GeoPoint,
    *,
    requested_start: datetime,
    requested_end: datetime,
    elevation_m: float | None,
    models: str | None,
) -> dict[str, str | float]:
    params: dict[str, str | float] = {
        "latitude": location.latitude_deg,
        "longitude": location.longitude_deg,
        "hourly": ",".join(_HOURLY_FIELDS),
        "timezone": "UTC",
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
        "start_date": requested_start.date().isoformat(),
        "end_date": requested_end.date().isoformat(),
    }
    if elevation_m is not None:
        params["elevation"] = float(elevation_m)
    if models:
        params["models"] = models
    return params


def _decode_payload(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataSourceError("Open-Meteo returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DataSourceError("Open-Meteo response is not a JSON object")
    if "error" in payload:
        raise DataSourceError(f"Open-Meteo error: {payload.get('reason', payload['error'])}")
    return payload


def _hourly_arrays(payload: dict[str, Any]) -> tuple[list[Any], dict[str, list[Any]]]:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise DataSourceError("Open-Meteo response has no hourly data")
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise DataSourceError("Open-Meteo hourly response has no times")

    arrays: dict[str, list[Any]] = {}
    for field in _HOURLY_FIELDS:
        values = hourly.get(field)
        if not isinstance(values, list) or len(values) != len(times):
            raise DataSourceError(f"Open-Meteo hourly field {field!r} is missing or misaligned")
        arrays[field] = values
    return times, arrays


def _clamped_number(value: Any, *, field: str, lower: float, upper: float) -> float:
    return min(upper, max(lower, _number(value, field=field)))


def _point_from_hourly(
    when: datetime,
    index: int,
    arrays: dict[str, list[Any]],
) -> WeatherSample:
    wind_direction = _optional_number(arrays["wind_direction_10m"][index])
    if wind_direction is not None:
        wind_direction %= 360.0

    return WeatherSample(
        time=when,
        air_temperature_c=_number(
            arrays["temperature_2m"][index],
            field="temperature_2m",
        ),
        relative_humidity_pct=_clamped_number(
            arrays["relative_humidity_2m"][index],
            field="relative_humidity_2m",
            lower=0.0,
            upper=100.0,
        ),
        wind_speed_m_s=max(
            0.0,
            _number(
                arrays["wind_speed_10m"][index],
                field="wind_speed_10m",
            ),
        ),
        direct_normal_irradiance_w_m2=max(
            0.0,
            _number(
                arrays["direct_normal_irradiance_instant"][index],
                field="direct_normal_irradiance_instant",
            ),
        ),
        diffuse_horizontal_irradiance_w_m2=max(
            0.0,
            _number(
                arrays["diffuse_radiation_instant"][index],
                field="diffuse_radiation_instant",
            ),
        ),
        cloud_fraction=_clamped_number(
            arrays["cloud_cover"][index],
            field="cloud_cover",
            lower=0.0,
            upper=100.0,
        )
        / 100.0,
        pressure_pa=max(
            1.0,
            100.0
            * _number(
                arrays["surface_pressure"][index],
                field="surface_pressure",
            ),
        ),
        precipitation_mm_h=max(
            0.0,
            _number(
                arrays["precipitation"][index],
                field="precipitation",
            ),
        ),
        wind_direction_deg=wind_direction,
    )


def _weather_points(
    times: list[Any],
    arrays: dict[str, list[Any]],
    *,
    requested_start: datetime,
    requested_end: datetime,
) -> tuple[WeatherSample, ...]:
    points: list[WeatherSample] = []
    lower = requested_start - timedelta(hours=1)
    upper = requested_end + timedelta(hours=1)
    for index, raw_time in enumerate(times):
        if not isinstance(raw_time, str):
            raise DataSourceError("Open-Meteo returned a non-string hourly time")
        when = _parse_utc_time(raw_time)
        if lower <= when <= upper:
            points.append(_point_from_hourly(when, index, arrays))
    if not points:
        raise DataSourceError("Open-Meteo returned no points in the requested time range")
    return tuple(points)


@dataclass(frozen=True, slots=True)
class OpenMeteoWeatherSource:
    """Retrieve normalized meteorological samples from Open-Meteo."""

    http: HttpGetter
    endpoint: str = OPEN_METEO_FORECAST_URL
    models: str | None = None
    cache_ttl_s: float = 900.0

    def fetch(
        self,
        location: GeoPoint,
        *,
        start: datetime,
        end: datetime,
        history: timedelta = timedelta(hours=12),
        elevation_m: float | None = None,
    ) -> OpenMeteoWeatherResult:
        validate_time_window(start, end)
        if history.total_seconds() < 0:
            raise ValueError("history cannot be negative")
        _validate_elevation(elevation_m)

        requested_start = (start - history).astimezone(UTC)
        requested_end = end.astimezone(UTC)
        params = _request_params(
            location,
            requested_start=requested_start,
            requested_end=requested_end,
            elevation_m=elevation_m,
            models=self.models,
        )
        payload = _decode_payload(
            self.http.get(self.endpoint, params=params, ttl_s=self.cache_ttl_s)
        )
        times, arrays = _hourly_arrays(payload)
        points = _weather_points(
            times,
            arrays,
            requested_start=requested_start,
            requested_end=requested_end,
        )

        model_value = payload.get("model")
        model = model_value if isinstance(model_value, str) else self.models
        return OpenMeteoWeatherResult(
            samples=points,
            model=model,
            model_elevation_m=_optional_number(payload.get("elevation")),
            generation_time_ms=_optional_number(payload.get("generationtime_ms")),
        )
