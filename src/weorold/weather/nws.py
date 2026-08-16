from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from weorold._transport import HttpGetter
from weorold._validation import validate_time_window
from weorold.errors import DataSourceError
from weorold.models import GeoPoint
from weorold.weather._psychrometrics import (
    relative_humidity_from_vapor_pressure_pct,
    saturation_vapor_pressure_pa,
)
from weorold.weather.models import WeatherSample

NWS_API_ROOT = "https://api.weather.gov"
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


@dataclass(frozen=True, slots=True)
class NwsWeatherResult:
    samples: tuple[WeatherSample, ...]
    grid_url: str
    office: str | None
    grid_x: int | None
    grid_y: int | None


@dataclass(frozen=True, slots=True)
class _GridValue:
    start: datetime
    end: datetime
    value: float | None


@dataclass(frozen=True, slots=True)
class _GridSeries:
    uom: str | None
    values: tuple[_GridValue, ...]

    def at(self, when: datetime) -> tuple[float | None, float | None]:
        for index, item in enumerate(self.values):
            is_last_endpoint = index == len(self.values) - 1 and when == item.end
            if item.start <= when < item.end or is_last_endpoint:
                duration_h = (item.end - item.start).total_seconds() / 3600.0
                return item.value, duration_h
        return None, None


def _parse_duration(value: str) -> timedelta:
    match = _DURATION_RE.fullmatch(value)
    if match is None:
        raise DataSourceError(f"unsupported NWS ISO-8601 duration {value!r}")
    parts = {name: float(text or 0.0) for name, text in match.groupdict().items()}
    return timedelta(
        days=parts["days"],
        hours=parts["hours"],
        minutes=parts["minutes"],
        seconds=parts["seconds"],
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DataSourceError("NWS validTime start is not timezone-aware")
    return parsed.astimezone(UTC)


def _parse_series(properties: dict[str, Any], name: str) -> _GridSeries:
    raw = properties.get(name)
    if not isinstance(raw, dict):
        return _GridSeries(None, ())
    values = raw.get("values")
    if not isinstance(values, list):
        return _GridSeries(raw.get("uom") if isinstance(raw.get("uom"), str) else None, ())
    parsed: list[_GridValue] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        valid_time = item.get("validTime")
        if not isinstance(valid_time, str) or "/" not in valid_time:
            continue
        start_text, duration_text = valid_time.split("/", 1)
        start = _parse_time(start_text)
        end = start + _parse_duration(duration_text)
        raw_value = item.get("value")
        numeric = (
            float(raw_value)
            if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool)
            else None
        )
        parsed.append(_GridValue(start, end, numeric))
    return _GridSeries(
        raw.get("uom") if isinstance(raw.get("uom"), str) else None,
        tuple(parsed),
    )


def _temperature_c(value: float | None, uom: str | None) -> float | None:
    if value is None:
        return None
    if uom in {"wmoUnit:degC", "unit:degC", None}:
        return value
    if uom in {"wmoUnit:degF", "unit:degF"}:
        return (value - 32.0) * 5.0 / 9.0
    if uom in {"wmoUnit:K", "unit:K"}:
        return value - 273.15
    raise DataSourceError(f"unsupported NWS temperature unit {uom!r}")


def _wind_m_s(value: float | None, uom: str | None) -> float | None:
    if value is None:
        return None
    if uom in {"wmoUnit:km_h-1", "unit:km_h-1"}:
        return value / 3.6
    if uom in {"wmoUnit:m_s-1", "unit:m_s-1", None}:
        return value
    if uom in {"wmoUnit:kn", "unit:kn"}:
        return value * 0.514444
    raise DataSourceError(f"unsupported NWS wind-speed unit {uom!r}")


def _json(http: HttpGetter, url: str, *, ttl_s: float) -> dict[str, Any]:
    try:
        payload = json.loads(
            http.get(
                url,
                headers={"Accept": "application/geo+json"},
                ttl_s=ttl_s,
            )
        )
    except json.JSONDecodeError as exc:
        raise DataSourceError(f"invalid JSON returned by {url}") from exc
    if not isinstance(payload, dict):
        raise DataSourceError(f"NWS response from {url} is not an object")
    return payload


@dataclass(frozen=True, slots=True)
class NwsWeatherSource:
    """Retrieve official NWS gridded forecast data for a U.S. point."""

    http: HttpGetter
    api_root: str = NWS_API_ROOT
    cache_ttl_s: float = 600.0

    def fetch(
        self,
        location: GeoPoint,
        *,
        start: datetime,
        end: datetime,
        step: timedelta = timedelta(hours=1),
    ) -> NwsWeatherResult:
        validate_time_window(start, end)
        if step.total_seconds() <= 0:
            raise ValueError("step must be positive")

        point_url = (
            f"{self.api_root.rstrip('/')}/points/"
            f"{location.latitude_deg:.6f},{location.longitude_deg:.6f}"
        )
        point = _json(self.http, point_url, ttl_s=24 * 3600.0)
        point_properties = point.get("properties")
        if not isinstance(point_properties, dict):
            raise DataSourceError("NWS /points response lacks properties")
        grid_url = point_properties.get("forecastGridData")
        if not isinstance(grid_url, str) or not grid_url:
            raise DataSourceError("NWS /points response lacks forecastGridData")
        grid = _json(self.http, grid_url, ttl_s=self.cache_ttl_s)
        properties = grid.get("properties")
        if not isinstance(properties, dict):
            raise DataSourceError("NWS grid response lacks properties")

        temp = _parse_series(properties, "temperature")
        dew = _parse_series(properties, "dewpoint")
        rh = _parse_series(properties, "relativeHumidity")
        wind = _parse_series(properties, "windSpeed")
        direction = _parse_series(properties, "windDirection")
        cloud = _parse_series(properties, "skyCover")
        precip = _parse_series(properties, "quantitativePrecipitation")

        utc_start = start.astimezone(UTC)
        utc_end = end.astimezone(UTC)
        now = utc_start
        points: list[WeatherSample] = []
        while now <= utc_end:
            temp_raw, _ = temp.at(now)
            air_temp = _temperature_c(temp_raw, temp.uom)
            if air_temp is None:
                raise DataSourceError(f"NWS grid has no temperature at {now.isoformat()}")
            rh_raw, _ = rh.at(now)
            if rh_raw is None:
                dew_raw, _ = dew.at(now)
                dew_c = _temperature_c(dew_raw, dew.uom)
                if dew_c is None:
                    raise DataSourceError(f"NWS grid has no humidity/dewpoint at {now.isoformat()}")
                rh_value = relative_humidity_from_vapor_pressure_pct(
                    air_temp,
                    saturation_vapor_pressure_pa(dew_c),
                )
            else:
                rh_value = rh_raw
            wind_raw, _ = wind.at(now)
            wind_value = _wind_m_s(wind_raw, wind.uom)
            cloud_raw, _ = cloud.at(now)
            cloud_fraction = min(1.0, max(0.0, (cloud_raw or 0.0) / 100.0))
            precipitation, precip_duration_h = precip.at(now)
            precip_rate = 0.0
            if precipitation is not None and precip_duration_h and precip_duration_h > 0:
                precip_rate = max(0.0, precipitation / precip_duration_h)
            direction_raw, _ = direction.at(now)
            points.append(
                WeatherSample(
                    time=now,
                    air_temperature_c=air_temp,
                    relative_humidity_pct=min(100.0, max(0.0, rh_value)),
                    wind_speed_m_s=max(0.0, wind_value or 0.0),
                    wind_direction_deg=(
                        direction_raw % 360.0 if direction_raw is not None else None
                    ),
                    precipitation_mm_h=precip_rate,
                    cloud_fraction=cloud_fraction,
                    pressure_pa=None,
                    direct_normal_irradiance_w_m2=None,
                    diffuse_horizontal_irradiance_w_m2=None,
                )
            )
            now += step

        office = point_properties.get("gridId")
        grid_x = point_properties.get("gridX")
        grid_y = point_properties.get("gridY")
        return NwsWeatherResult(
            samples=tuple(points),
            grid_url=grid_url,
            office=office if isinstance(office, str) else None,
            grid_x=int(grid_x) if isinstance(grid_x, int) else None,
            grid_y=int(grid_y) if isinstance(grid_y, int) else None,
        )
