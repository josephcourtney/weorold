from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from math import cos, radians, sqrt

from weorold._transport import HttpGetter
from weorold.errors import DataSourceError
from weorold.models import GeoPoint

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"


@dataclass(frozen=True, slots=True)
class OsmWaySurface:
    way_id: int
    tags: dict[str, str]
    geometry: tuple[GeoPoint, ...]


@dataclass(frozen=True, slots=True)
class OsmSurfaceMatch:
    surface_key: str | None
    distance_m: float
    way_id: int
    tags: dict[str, str]


_SURFACE_KEYS: dict[str, str] = {
    "asphalt": "asphalt",
    "concrete": "asphalt",
    "concrete:plates": "asphalt",
    "concrete:lanes": "asphalt",
    "paving_stones": "asphalt",
    "sett": "rock",
    "cobblestone": "rock",
    "unhewn_cobblestone": "rock",
    "stone": "rock",
    "rock": "rock",
    "pebblestone": "rock",
    "gravel": "soil",
    "fine_gravel": "soil",
    "compacted": "soil",
    "dirt": "soil",
    "earth": "soil",
    "ground": "soil",
    "mud": "soil",
    "grass": "grass",
    "grass_paver": "grass",
    "sand": "sand",
}


def _bbox(
    points: Sequence[GeoPoint],
    buffer_m: float,
) -> tuple[float, float, float, float]:
    if not points:
        msg = "points must not be empty"
        raise ValueError(msg)

    lats = [point.latitude_deg for point in points]
    lons = [point.longitude_deg for point in points]

    mean_lat = sum(lats) / len(lats)
    lat_buffer = buffer_m / 111_320.0
    lon_buffer = buffer_m / max(
        1.0,
        111_320.0 * cos(radians(mean_lat)),
    )

    return (
        min(lats) - lat_buffer,
        min(lons) - lon_buffer,
        max(lats) + lat_buffer,
        max(lons) + lon_buffer,
    )


def _local_xy_m(point: GeoPoint, origin: GeoPoint) -> tuple[float, float]:
    lat_scale = 111_320.0
    lon_scale = lat_scale * cos(radians(origin.latitude_deg))
    return (
        (point.longitude_deg - origin.longitude_deg) * lon_scale,
        (point.latitude_deg - origin.latitude_deg) * lat_scale,
    )


def _point_segment_distance_m(point: GeoPoint, a: GeoPoint, b: GeoPoint) -> float:
    ax, ay = _local_xy_m(a, point)
    bx, by = _local_xy_m(b, point)
    vx = bx - ax
    vy = by - ay
    length_sq = vx * vx + vy * vy
    if length_sq <= 1e-12:
        return sqrt(ax * ax + ay * ay)
    t = min(1.0, max(0.0, -(ax * vx + ay * vy) / length_sq))
    x = ax + t * vx
    y = ay + t * vy
    return sqrt(x * x + y * y)


def _surface_key(tags: dict[str, str]) -> str | None:
    surface = tags.get("surface", "").lower()
    if surface in _SURFACE_KEYS:
        return _SURFACE_KEYS[surface]
    if tags.get("highway") in {"primary", "secondary", "tertiary", "residential", "service"}:
        return "asphalt"
    return None


@dataclass(frozen=True, slots=True)
class OsmRouteSurfaceSource:
    """Retrieve nearby OSM ways and use their tags as trail/surface observations."""

    http: HttpGetter
    endpoint: str = OVERPASS_API_URL
    search_buffer_m: float = 120.0
    match_radius_m: float = 45.0
    cache_ttl_s: float = 7 * 24 * 3600.0

    def fetch(self, points: Sequence[GeoPoint]) -> tuple[OsmWaySurface, ...]:
        if self.search_buffer_m <= 0 or self.match_radius_m <= 0:
            raise ValueError("OSM search and match radii must be positive")
        south, west, north, east = _bbox(points, self.search_buffer_m)
        query = (
            "[out:json][timeout:30];"
            f'(way["highway"]({south:.7f},{west:.7f},{north:.7f},{east:.7f}););'
            "out tags geom;"
        )
        try:
            payload = json.loads(
                self.http.get(
                    self.endpoint,
                    params={"data": query},
                    ttl_s=self.cache_ttl_s,
                )
            )
        except json.JSONDecodeError as exc:
            raise DataSourceError("Overpass returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise DataSourceError("Overpass response is not an object")
        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise DataSourceError("Overpass response has no elements array")
        ways: list[OsmWaySurface] = []
        for element in elements:
            if not isinstance(element, dict) or element.get("type") != "way":
                continue
            raw_id = element.get("id")
            if not isinstance(raw_id, int):
                continue
            raw_tags = element.get("tags")
            tags = (
                {str(key): str(value) for key, value in raw_tags.items()}
                if isinstance(raw_tags, dict)
                else {}
            )
            raw_geometry = element.get("geometry")
            if not isinstance(raw_geometry, list):
                continue
            geometry: list[GeoPoint] = []
            for raw_point in raw_geometry:
                if not isinstance(raw_point, dict):
                    continue
                lat = raw_point.get("lat")
                lon = raw_point.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    geometry.append(GeoPoint(float(lat), float(lon)))
            if len(geometry) >= 2:
                ways.append(OsmWaySurface(raw_id, tags, tuple(geometry)))
        return tuple(ways)

    def build_matcher(self, points: Sequence[GeoPoint]) -> OsmSurfaceMatcher:
        return OsmSurfaceMatcher(self.fetch(points), match_radius_m=self.match_radius_m)


@dataclass(frozen=True, slots=True)
class OsmSurfaceMatcher:
    ways: tuple[OsmWaySurface, ...]
    match_radius_m: float = 45.0

    def match(self, point: GeoPoint) -> OsmSurfaceMatch | None:
        best_way: OsmWaySurface | None = None
        best_distance = float("inf")
        for way in self.ways:
            for start, end in zip(way.geometry, way.geometry[1:], strict=False):
                distance = _point_segment_distance_m(point, start, end)
                if distance < best_distance:
                    best_distance = distance
                    best_way = way
        if best_way is None or best_distance > self.match_radius_m:
            return None
        return OsmSurfaceMatch(
            surface_key=_surface_key(best_way.tags),
            distance_m=best_distance,
            way_id=best_way.way_id,
            tags=best_way.tags,
        )

    def surface_key_at(self, point: GeoPoint) -> str | None:
        match = self.match(point)
        return None if match is None else match.surface_key
