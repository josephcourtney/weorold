from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class WeatherSample:
    """Provider-neutral meteorological observation or forecast sample."""

    time: datetime
    air_temperature_c: float
    relative_humidity_pct: float | None = None
    wind_speed_m_s: float | None = None
    wind_direction_deg: float | None = None
    precipitation_mm_h: float | None = None
    cloud_fraction: float | None = None
    pressure_pa: float | None = None
    direct_normal_irradiance_w_m2: float | None = None
    diffuse_horizontal_irradiance_w_m2: float | None = None
