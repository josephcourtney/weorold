from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from weorold._transport import HttpGetter
from weorold.errors import DataSourceError
from weorold.models import GeoPoint

from .mrlc import GeoServerWmsPointSource, WmsLayerSelection

LANDFIRE_2025_CONUS_WMS = "https://edcintl.cr.usgs.gov/geoserver/landfire/conus_2025/ows"
LANDFIRE_2024_CONUS_WMS = "https://edcintl.cr.usgs.gov/geoserver/landfire/conus_2024/ows"
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _text(node: ET.Element, local_name: str) -> str | None:
    for child in node:
        if child.tag.rsplit("}", 1)[-1] == local_name and child.text:
            return child.text.strip()
    return None


def _layer_score(name: str, title: str, *, abbreviation: str, phrase: str) -> int:
    words = set(_TOKEN_RE.findall(f"{name} {title}".lower()))
    normalized = " ".join(_TOKEN_RE.findall(f"{name} {title}".lower()))
    score = 0
    if abbreviation.lower() in words:
        score += 3
    if phrase.lower() in normalized:
        score += 10
    # Prefer layers whose title/name ends with the product abbreviation; this is
    # common in LANDFIRE layer names without matching arbitrary substrings such as
    # the "ch" in unrelated words.
    if _TOKEN_RE.findall(name.lower())[-1:] == [abbreviation.lower()]:
        score += 4
    return score


def _resolve_product_layer(
    http: HttpGetter,
    service_url: str,
    *,
    abbreviation: str,
    phrase: str,
) -> WmsLayerSelection:
    raw = http.get(
        service_url,
        params={"service": "WMS", "request": "GetCapabilities", "version": "1.1.1"},
        ttl_s=30 * 24 * 3600.0,
    )
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DataSourceError("invalid LANDFIRE WMS capabilities") from exc
    candidates: list[tuple[int, WmsLayerSelection]] = []
    for layer in root.iter():
        if layer.tag.rsplit("}", 1)[-1] != "Layer":
            continue
        name = _text(layer, "Name")
        if not name:
            continue
        title = _text(layer, "Title") or name
        score = _layer_score(name, title, abbreviation=abbreviation, phrase=phrase)
        if score:
            candidates.append((score, WmsLayerSelection(name, title)))
    if not candidates:
        raise DataSourceError(f"LANDFIRE WMS exposes no layer matching {phrase!r}/{abbreviation!r}")
    return max(candidates, key=lambda item: (item[0], item[1].name))[1]


@dataclass(frozen=True, slots=True)
class LandfireCanopyHeightSource:
    """LANDFIRE forest canopy top and base height in meters.

    LANDFIRE CH and CBH pixels are encoded as meters * 10. These layers are
    forest-specific; non-forest cells legitimately return no usable height.
    """

    http: HttpGetter
    service_url: str = LANDFIRE_2025_CONUS_WMS
    canopy_height_layer: str | None = None
    canopy_base_height_layer: str | None = None

    def _selection(self, *, base: bool) -> WmsLayerSelection:
        explicit = self.canopy_base_height_layer if base else self.canopy_height_layer
        if explicit is not None:
            return WmsLayerSelection(explicit, explicit)
        return _resolve_product_layer(
            self.http,
            self.service_url,
            abbreviation="CBH" if base else "CH",
            phrase="canopy base height" if base else "canopy height",
        )

    @staticmethod
    def _meters(raw: float | None) -> float | None:
        if raw is None or raw <= 0:
            return None
        return raw / 10.0

    def sample_many(
        self,
        points: list[GeoPoint],
    ) -> tuple[
        tuple[float | None, ...],
        tuple[float | None, ...],
        tuple[WmsLayerSelection, WmsLayerSelection],
    ]:
        height_selection = self._selection(base=False)
        base_selection = self._selection(base=True)
        source = GeoServerWmsPointSource(self.http, self.service_url)
        heights = tuple(
            self._meters(source.sample(point, selection=height_selection)) for point in points
        )
        bases = tuple(
            self._meters(source.sample(point, selection=base_selection)) for point in points
        )
        return heights, bases, (height_selection, base_selection)


def decode_existing_vegetation_height_m(raw: float | None) -> float | None:
    """Decode the LANDFIRE EVH VALUE field into representative height in meters.

    LF2025 EVH uses separate integer ranges for tree, shrub, and herbaceous
    height classes. Developed/crop/non-vegetated class codes do not encode a
    physical vegetation height and therefore return ``None``.
    """
    if raw is None:
        return None
    value = round(raw)
    if 101 <= value <= 199:
        return float(value - 100)
    if 201 <= value <= 230:
        return (value - 200) / 10.0
    if 301 <= value <= 310:
        return (value - 300) / 10.0
    return None


@dataclass(frozen=True, slots=True)
class LandfireVegetationHeightSource:
    """LANDFIRE Existing Vegetation Height (EVH) representative height."""

    http: HttpGetter
    service_url: str = LANDFIRE_2025_CONUS_WMS
    layer_name: str | None = None

    def _selection(self) -> WmsLayerSelection:
        if self.layer_name is not None:
            return WmsLayerSelection(self.layer_name, self.layer_name)
        return _resolve_product_layer(
            self.http,
            self.service_url,
            abbreviation="EVH",
            phrase="existing vegetation height",
        )

    def sample_many(
        self,
        points: list[GeoPoint],
    ) -> tuple[tuple[float | None, ...], WmsLayerSelection]:
        selection = self._selection()
        source = GeoServerWmsPointSource(self.http, self.service_url)
        values = tuple(
            decode_existing_vegetation_height_m(source.sample(point, selection=selection))
            for point in points
        )
        return values, selection
