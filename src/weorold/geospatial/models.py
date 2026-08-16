from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class LandCoverClass(Enum):
    OPEN_WATER = "open_water"
    DEVELOPED = "developed"
    BARREN = "barren"
    DECIDUOUS_FOREST = "deciduous_forest"
    EVERGREEN_FOREST = "evergreen_forest"
    MIXED_FOREST = "mixed_forest"
    SHRUB = "shrub"
    GRASSLAND = "grassland"
    PASTURE = "pasture"
    CULTIVATED = "cultivated"
    WETLAND = "wetland"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SmapMoistureSample:
    surface_vwc: float
    root_zone_vwc: float
    granule_id: str
    granule_time: datetime


@dataclass(frozen=True, slots=True)
class LidarPoint:
    x_m: float
    y_m: float
    elevation_m: float
    classification: int | None


@dataclass(frozen=True, slots=True)
class SsurgoHorizon:
    mukey: str
    map_unit_name: str
    component_key: str
    component_name: str
    component_pct: float | None
    top_cm: float | None
    bottom_cm: float | None
    sand_pct: float | None
    clay_pct: float | None
    organic_matter_pct: float | None
    bulk_density_g_cm3: float | None
    ksat_um_s: float | None
    available_water_capacity: float | None
    field_capacity_pct: float | None
    wilting_point_pct: float | None
    saturation_pct: float | None


@dataclass(frozen=True, slots=True)
class SsurgoProfile:
    horizons: tuple[SsurgoHorizon, ...]
