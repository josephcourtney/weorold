from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from weorold.transport import HttpGetter
from weorold.errors import DataSourceError
from weorold.geospatial.models import LandCoverClass
from weorold.models import GeoPoint

MRLC_LAND_COVER_WMS = (
    "https://dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data/wms"
)
MRLC_TREE_CANOPY_WMS = (
    "https://dmsdata.cr.usgs.gov/geoserver/mrlc_NLCD-Tree-Canopy-Native_conus_year_data/wms"
)
MRLC_IMPERVIOUS_WMS = (
    "https://dmsdata.cr.usgs.gov/geoserver/"
    "mrlc_Fractional-Impervious-Surface-Native_conus_year_data/wms"
)
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


@dataclass(frozen=True, slots=True)
class WmsLayerSelection:
    name: str
    title: str
    time_value: str | None = None


def _child_text(node: ET.Element, local_name: str) -> str | None:
    for child in node:
        if child.tag.rsplit("}", 1)[-1] == local_name and child.text:
            return child.text.strip()
    return None


def _years(text: str) -> tuple[int, ...]:
    return tuple(int(match.group(1)) for match in _YEAR_RE.finditer(text))


def _latest_time_value(text: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for token in re.split(r"[,\s]+", text.strip()):
        if not token:
            continue
        # WMS time dimensions may be a comma-separated list or an interval
        # ``start/end/period``. GetFeatureInfo wants an instant, so select the
        # latest dated endpoint rather than passing a whole interval.
        pieces = token.split("/")[:2] if "/" in token else [token]
        for piece in pieces:
            years = _years(piece)
            if years:
                candidates.append((max(years), piece))
    return max(candidates)[1] if candidates else None


@dataclass(frozen=True, slots=True)
class GeoServerWmsPointSource:
    """Sample a GeoServer raster through WMS GetFeatureInfo.

    MRLC currently publishes Annual NLCD and Tree Canopy through OGC WMS.  The
    adapter discovers the newest year exposed by the service unless a layer is
    pinned explicitly.
    """

    http: HttpGetter
    service_url: str
    layer_name: str | None = None
    cache_ttl_s: float = 30 * 24 * 3600.0
    pixel_radius_deg: float = 0.00035

    def _capabilities(self) -> bytes:
        return self.http.get(
            self.service_url,
            params={
                "service": "WMS",
                "request": "GetCapabilities",
                "version": "1.1.1",
            },
            ttl_s=self.cache_ttl_s,
        )

    def resolve_layer(self) -> WmsLayerSelection:
        try:
            root = ET.fromstring(self._capabilities())
        except ET.ParseError as exc:
            raise DataSourceError(f"invalid WMS capabilities from {self.service_url}") from exc
        candidates: list[WmsLayerSelection] = []
        for layer in root.iter():
            if layer.tag.rsplit("}", 1)[-1] != "Layer":
                continue
            name = _child_text(layer, "Name")
            if not name:
                continue
            title = _child_text(layer, "Title") or name
            if self.layer_name is not None and name != self.layer_name:
                continue
            time_value: str | None = None
            for child in layer:
                local = child.tag.rsplit("}", 1)[-1]
                if local not in {"Dimension", "Extent"}:
                    continue
                if child.attrib.get("name", "").lower() == "time" and child.text:
                    time_value = _latest_time_value(child.text)
            candidates.append(WmsLayerSelection(name, title, time_value))
        if not candidates:
            target = f" layer {self.layer_name!r}" if self.layer_name else " a queryable layer"
            raise DataSourceError(f"WMS capabilities do not expose{target}")
        if self.layer_name is not None:
            return candidates[0]

        def rank(candidate: WmsLayerSelection) -> tuple[int, int, str]:
            layer_years = _years(f"{candidate.name} {candidate.title}")
            time_years = _years(candidate.time_value or "")
            return (
                max((*layer_years, *time_years), default=-1),
                len(layer_years) + len(time_years),
                candidate.name,
            )

        return max(candidates, key=rank)

    @staticmethod
    def _numeric_feature_value(payload: object) -> float | None:
        if not isinstance(payload, dict):
            return None
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            return None
        feature = features[0]
        if not isinstance(feature, dict):
            return None
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            return None
        preferred = (
            "GRAY_INDEX",
            "gray_index",
            "VALUE",
            "Value",
            "value",
            "Pixel Value",
        )
        for key in (*preferred, *properties.keys()):
            value = properties.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    continue
        return None

    def sample(
        self,
        point: GeoPoint,
        *,
        selection: WmsLayerSelection | None = None,
    ) -> float | None:
        selected = selection or self.resolve_layer()
        radius = self.pixel_radius_deg
        params: dict[str, str | int | float] = {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetFeatureInfo",
            "layers": selected.name,
            "query_layers": selected.name,
            "styles": "",
            "srs": "EPSG:4326",
            "bbox": (
                f"{point.longitude_deg - radius},{point.latitude_deg - radius},"
                f"{point.longitude_deg + radius},{point.latitude_deg + radius}"
            ),
            "width": 3,
            "height": 3,
            "x": 1,
            "y": 1,
            "info_format": "application/json",
            "feature_count": 1,
        }
        if selected.time_value is not None:
            params["time"] = selected.time_value
        raw = self.http.get(self.service_url, params=params, ttl_s=self.cache_ttl_s)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            text = raw.decode("utf-8", errors="replace")
            match = re.search(
                r"(?:GRAY_INDEX|VALUE|Value|value|Pixel Value)\s*[=:]\s*"
                r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
                text,
            )
            if match is None:
                raise DataSourceError(
                    "WMS GetFeatureInfo returned no parseable raster value"
                ) from None
            return float(match.group(1))
        return self._numeric_feature_value(payload)


_NLCD_CLASS_MAP: dict[int, LandCoverClass] = {
    11: LandCoverClass.OPEN_WATER,
    21: LandCoverClass.DEVELOPED,
    22: LandCoverClass.DEVELOPED,
    23: LandCoverClass.DEVELOPED,
    24: LandCoverClass.DEVELOPED,
    31: LandCoverClass.BARREN,
    41: LandCoverClass.DECIDUOUS_FOREST,
    42: LandCoverClass.EVERGREEN_FOREST,
    43: LandCoverClass.MIXED_FOREST,
    52: LandCoverClass.SHRUB,
    71: LandCoverClass.GRASSLAND,
    81: LandCoverClass.PASTURE,
    82: LandCoverClass.CULTIVATED,
    90: LandCoverClass.WETLAND,
    95: LandCoverClass.WETLAND,
}


class _MrlcWmsSource:
    http: HttpGetter
    service_url: str
    layer_name: str | None

    def _source(self) -> GeoServerWmsPointSource:
        return GeoServerWmsPointSource(self.http, self.service_url, self.layer_name)

    def resolve_layer(self) -> WmsLayerSelection:
        return self._source().resolve_layer()


class _MrlcFractionSource(_MrlcWmsSource):
    def sample_many(
        self,
        points: list[GeoPoint],
        *,
        selection: WmsLayerSelection | None = None,
    ) -> tuple[float | None, ...]:
        source = self._source()
        layer = selection or source.resolve_layer()
        return tuple(
            _normalized_fraction(source.sample(point, selection=layer)) for point in points
        )


def _normalized_fraction(raw: float | None) -> float | None:
    return None if raw is None else min(1.0, max(0.0, raw / 100.0))


@dataclass(frozen=True, slots=True)
class MrlcLandCoverSource(_MrlcWmsSource):
    http: HttpGetter
    service_url: str = MRLC_LAND_COVER_WMS
    layer_name: str | None = None

    def sample_many(
        self,
        points: list[GeoPoint],
        *,
        selection: WmsLayerSelection | None = None,
    ) -> tuple[LandCoverClass, ...]:
        source = self._source()
        layer = selection or source.resolve_layer()
        values: list[LandCoverClass] = []
        for point in points:
            raw = source.sample(point, selection=layer)
            code = round(raw) if raw is not None else -1
            values.append(_NLCD_CLASS_MAP.get(code, LandCoverClass.UNKNOWN))
        return tuple(values)


@dataclass(frozen=True, slots=True)
class MrlcTreeCanopySource(_MrlcFractionSource):
    http: HttpGetter
    service_url: str = MRLC_TREE_CANOPY_WMS
    layer_name: str | None = None


@dataclass(frozen=True, slots=True)
class MrlcImperviousSource(_MrlcFractionSource):
    """Sample Annual NLCD fractional impervious surface as a [0, 1] fraction."""

    http: HttpGetter
    service_url: str = MRLC_IMPERVIOUS_WMS
    layer_name: str | None = None
