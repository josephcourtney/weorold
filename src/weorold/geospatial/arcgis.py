from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from weorold._transport import HttpGetter
from weorold.errors import DataSourceError
from weorold.models import GeoPoint

USGS_3DEP_IMAGE_SERVER = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
)


def _point_key(point: GeoPoint) -> tuple[float, float]:
    return round(point.latitude_deg, 7), round(point.longitude_deg, 7)


def _first_numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        for token in value.replace(",", " ").split():
            try:
                return float(token)
            except ValueError:
                continue
    return None


@dataclass(frozen=True, slots=True)
class ArcGisImageSampleSource:
    """Batch point sampler for a public ArcGIS ImageServer."""

    http: HttpGetter
    image_server_url: str
    cache_ttl_s: float = 30 * 24 * 3600.0
    max_batch_size: int = 900

    def __post_init__(self) -> None:
        if self.max_batch_size <= 0 or self.max_batch_size > 1000:
            raise ValueError("max_batch_size must be in [1, 1000]")

    def _batch(self, points: list[GeoPoint]) -> dict[tuple[float, float], float | None]:
        geometry = {
            "points": [[point.longitude_deg, point.latitude_deg] for point in points],
            "spatialReference": {"wkid": 4326},
        }
        params = {
            "f": "json",
            "geometryType": "esriGeometryMultipoint",
            "geometry": json.dumps(geometry, separators=(",", ":")),
            "returnFirstValueOnly": "true",
            "outFields": "*",
        }
        try:
            payload = json.loads(
                self.http.get(
                    f"{self.image_server_url.rstrip('/')}/getSamples",
                    params=params,
                    ttl_s=self.cache_ttl_s,
                )
            )
        except json.JSONDecodeError as exc:
            raise DataSourceError(
                f"invalid JSON from ArcGIS ImageServer {self.image_server_url}"
            ) from exc
        if not isinstance(payload, dict):
            raise DataSourceError("ArcGIS getSamples response is not an object")
        if "error" in payload:
            raise DataSourceError(f"ArcGIS getSamples error: {payload['error']}")
        raw_samples = payload.get("samples")
        if not isinstance(raw_samples, list):
            raise DataSourceError("ArcGIS getSamples response has no samples array")

        result: dict[tuple[float, float], float | None] = {
            _point_key(point): None for point in points
        }
        # ArcGIS normally preserves multipoint order. Use returned locations when
        # present so sparse/no-data responses remain correctly associated.
        sequential = len(raw_samples) == len(points)
        for index, raw_sample in enumerate(raw_samples):
            if not isinstance(raw_sample, dict):
                continue
            value = _first_numeric(raw_sample.get("value"))
            location = raw_sample.get("location")
            key: tuple[float, float] | None = _point_key(points[index]) if sequential else None
            if key is None and isinstance(location, dict):
                x = location.get("x")
                y = location.get("y")
                spatial_reference = location.get("spatialReference")
                wkid = (
                    spatial_reference.get("wkid") if isinstance(spatial_reference, dict) else 4326
                )
                if (
                    wkid in {4326, 4269}
                    and isinstance(x, (int, float))
                    and isinstance(y, (int, float))
                ):
                    key = round(float(y), 7), round(float(x), 7)
            if key is not None:
                result[key] = value
        return result

    def sample_points(self, points: Iterable[GeoPoint]) -> dict[tuple[float, float], float | None]:
        unique: dict[tuple[float, float], GeoPoint] = {}
        for point in points:
            unique.setdefault(_point_key(point), point)
        ordered = list(unique.values())
        result: dict[tuple[float, float], float | None] = {}
        for start in range(0, len(ordered), self.max_batch_size):
            result.update(self._batch(ordered[start : start + self.max_batch_size]))
        return result


@dataclass(frozen=True, slots=True)
class SampledPointField:
    values: dict[tuple[float, float], float | None]

    def __call__(self, point: GeoPoint) -> float | None:
        return self.values.get(_point_key(point))


@dataclass(frozen=True, slots=True)
class Usgs3depElevationSource:
    http: HttpGetter
    image_server_url: str = USGS_3DEP_IMAGE_SERVER
    cache_ttl_s: float = 30 * 24 * 3600.0

    def fetch_field(self, points: Iterable[GeoPoint]) -> SampledPointField:
        sampler = ArcGisImageSampleSource(
            self.http,
            self.image_server_url,
            cache_ttl_s=self.cache_ttl_s,
        )
        return SampledPointField(sampler.sample_points(points))
