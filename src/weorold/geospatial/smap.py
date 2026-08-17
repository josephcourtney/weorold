from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from weorold.transport import HttpGetter
from weorold.errors import DataSourceError
from weorold.geospatial.models import SmapMoistureSample
from weorold.models import GeoPoint

NASA_CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
SMAP_L4_SHORT_NAME = "SPL4SMGP"
SMAP_L4_VERSION = "008"


def _numpy() -> Any:
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError as exc:
        msg = "SMAP sampling requires numpy; install weorold[advanced-data]"
        raise DataSourceError(msg) from exc

    return np


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC)


def _data_link(entry: dict[str, Any]) -> str | None:
    links = entry.get("links")
    if not isinstance(links, list):
        return None
    candidates: list[str] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        if link.get("inherited") is True:
            continue
        title = str(link.get("title", "")).lower()
        rel = str(link.get("rel", "")).lower()
        if "opendap" in title or "opendap" in href.lower() or "metadata" in rel:
            continue
        if href.lower().endswith((".h5", ".hdf5")) or "data#" in rel:
            candidates.append(href)
    return candidates[0] if candidates else None


def _find_dataset(group: Any, names: set[str]) -> Any | None:
    result = None

    def visitor(name: str, obj: Any) -> None:
        nonlocal result
        if result is not None:
            return
        if name.rsplit("/", 1)[-1].lower() in names and hasattr(obj, "shape"):
            result = obj

    group.visititems(visitor)
    return result


def _valid_scalar(dataset: Any, index: tuple[int, ...]) -> float | None:
    value = float(dataset[index])
    attrs = dataset.attrs
    for key in ("_FillValue", "missing_value"):
        if key in attrs:
            try:
                if value == float(attrs[key]):
                    return None
            except (TypeError, ValueError):
                pass
    if not -0.01 <= value <= 1.2:
        return None
    return value


def _nearest_index(handle: Any, field: Any, point: GeoPoint) -> tuple[int, ...]:
    np = _numpy()

    lat = _find_dataset(handle, {"cell_lat", "latitude", "lat"})
    lon = _find_dataset(handle, {"cell_lon", "longitude", "lon"})
    if (
        lat is not None
        and lon is not None
        and lat.shape == field.shape
        and lon.shape == field.shape
    ):
        lat_values = np.asarray(lat[...], dtype=float)
        lon_values = np.asarray(lon[...], dtype=float)
        distance = (lat_values - point.latitude_deg) ** 2 + (
            np.cos(np.deg2rad(point.latitude_deg)) * (lon_values - point.longitude_deg)
        ) ** 2
        flat = int(np.nanargmin(distance))
        return tuple(int(v) for v in np.unravel_index(flat, field.shape))

    x = _find_dataset(handle, {"x", "xcoord", "easting"})
    y = _find_dataset(handle, {"y", "ycoord", "northing"})
    if x is not None and y is not None and len(field.shape) == 2:
        try:
            from pyproj import Transformer  # noqa: PLC0415 # no cover - optional dependency
        except ImportError as exc:
            raise DataSourceError("SMAP EASE-grid sampling requires pyproj") from exc
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
        target_x, target_y = transformer.transform(point.longitude_deg, point.latitude_deg)
        xs = np.asarray(x[...], dtype=float).reshape(-1)
        ys = np.asarray(y[...], dtype=float).reshape(-1)
        ix = int(np.nanargmin(abs(xs - target_x)))
        iy = int(np.nanargmin(abs(ys - target_y)))
        # SMAP arrays conventionally use y,x ordering.
        return iy, ix
    raise DataSourceError("SMAP granule has no recognized latitude/longitude or EASE-grid axes")


@dataclass(frozen=True, slots=True)
class SmapL4Source:
    """Retrieve NASA SMAP L4 surface/root-zone moisture through CMR/Earthdata."""

    http: HttpGetter
    earthdata_token: str | None = None
    cmr_url: str = NASA_CMR_GRANULES_URL
    version: str = SMAP_L4_VERSION
    cache_ttl_s: float = 12 * 3600.0

    def _token(self) -> str:
        token = self.earthdata_token or os.environ.get("EARTHDATA_TOKEN")
        if not token:
            raise DataSourceError(
                "SMAP download requires an Earthdata bearer token; set EARTHDATA_TOKEN"
            )
        return token

    def _granule(self, point: GeoPoint, when: datetime) -> tuple[str, str, datetime]:
        when_utc = when.astimezone(UTC)
        start = when_utc - timedelta(hours=36)
        end = when_utc + timedelta(hours=3)
        raw = self.http.get(
            self.cmr_url,
            params={
                "short_name": SMAP_L4_SHORT_NAME,
                "version": self.version,
                "point": f"{point.longitude_deg},{point.latitude_deg}",
                "temporal": f"{start.isoformat().replace('+00:00', 'Z')},{end.isoformat().replace('+00:00', 'Z')}",
                "page_size": 50,
            },
            headers={"Accept": "application/json"},
            ttl_s=self.cache_ttl_s,
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DataSourceError("NASA CMR returned invalid JSON") from exc
        feed = payload.get("feed") if isinstance(payload, dict) else None
        entries = feed.get("entry") if isinstance(feed, dict) else None
        if not isinstance(entries, list) or not entries:
            raise DataSourceError("NASA CMR found no SMAP L4 granule near the requested time")
        candidates: list[tuple[float, str, str, datetime]] = []
        for raw_entry in entries:
            if not isinstance(raw_entry, dict):
                continue
            entry = raw_entry
            granule_time = _parse_time(entry.get("time_start"))
            link = _data_link(entry)
            if granule_time is None or link is None:
                continue
            granule_id = str(entry.get("producer_granule_id") or entry.get("id") or "SMAP")
            # Prefer observations at/before the simulated start. Future analyses
            # receive a substantial penalty rather than silently using information
            # that would not have been available yet.
            future_penalty = 72 * 3600 if granule_time > when_utc else 0
            distance = abs((when_utc - granule_time).total_seconds()) + future_penalty
            candidates.append((distance, granule_id, link, granule_time))
        if not candidates:
            raise DataSourceError("CMR SMAP entries contain no downloadable HDF5 granule")
        _, granule_id, link, granule_time = min(candidates, key=lambda item: item[0])
        return granule_id, link, granule_time

    def sample_many(
        self, points: list[GeoPoint], *, when: datetime
    ) -> tuple[SmapMoistureSample | None, ...]:
        if not points:
            return ()
        granule_id, link, granule_time = self._granule(points[0], when)
        payload = self.http.get(
            link,
            headers={"Authorization": f"Bearer {self._token()}"},
            ttl_s=self.cache_ttl_s,
        )
        try:
            import h5py  # noqa: PLC0415 # no cover - optional dependency
        except ImportError as exc:
            raise DataSourceError("SMAP sampling requires h5py") from exc
        with NamedTemporaryFile(suffix=".h5") as stream:
            stream.write(payload)
            stream.flush()
            try:
                handle = h5py.File(Path(stream.name), "r")
            except OSError as exc:
                raise DataSourceError(
                    "Earthdata response is not a readable SMAP HDF5 granule"
                ) from exc
            with handle:
                surface = _find_dataset(handle, {"sm_surface"})
                root = _find_dataset(handle, {"sm_rootzone", "sm_root_zone"})
                if surface is None or root is None:
                    raise DataSourceError("SMAP granule lacks sm_surface/sm_rootzone datasets")
                samples: list[SmapMoistureSample | None] = []
                for point in points:
                    index = _nearest_index(handle, surface, point)
                    surface_value = _valid_scalar(surface, index)
                    root_value = _valid_scalar(root, index)
                    if surface_value is None or root_value is None:
                        samples.append(None)
                        continue
                    samples.append(
                        SmapMoistureSample(
                            surface_vwc=surface_value,
                            root_zone_vwc=root_value,
                            granule_id=granule_id,
                            granule_time=granule_time,
                        )
                    )
                return tuple(samples)
