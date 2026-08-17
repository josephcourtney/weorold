from __future__ import annotations

import json

import pytest

from weorold import GeoPoint
from weorold.transport import HttpHeaders, QueryParams
from weorold.geospatial import (
    LandfireCanopyHeightSource,
    LandfireVegetationHeightSource,
    decode_existing_vegetation_height_m,
)


class _LandfireHttp:
    def get(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: HttpHeaders | None = None,
        ttl_s: float | None = None,
    ) -> bytes:
        del url, headers, ttl_s
        params = dict(params or {})
        if params.get("request") == "GetCapabilities":
            return b"""<WMT_MS_Capabilities><Capability><Layer>
              <Layer><Name>LF2025_EVT</Name><Title>Existing Vegetation Type</Title></Layer>
              <Layer><Name>LF2025_EVH</Name><Title>Existing Vegetation Height</Title></Layer>
              <Layer><Name>LF2025_CH</Name><Title>Forest Canopy Height</Title></Layer>
              <Layer><Name>LF2025_CBH</Name><Title>Forest Canopy Base Height</Title></Layer>
            </Layer></Capability></WMT_MS_Capabilities>"""
        layer = str(params.get("query_layers", ""))
        if layer.endswith("_EVH"):
            value = 118
        elif layer.endswith("_CH"):
            value = 185
        else:
            value = 55
        return json.dumps({"features": [{"properties": {"GRAY_INDEX": value}}]}).encode()


def test_landfire_existing_vegetation_height_decodes_tree_shrub_and_herb_classes() -> None:
    assert decode_existing_vegetation_height_m(118) == pytest.approx(18.0)
    assert decode_existing_vegetation_height_m(215) == pytest.approx(1.5)
    assert decode_existing_vegetation_height_m(307) == pytest.approx(0.7)
    assert decode_existing_vegetation_height_m(31) is None
    values, selection = LandfireVegetationHeightSource(_LandfireHttp()).sample_many(
        [GeoPoint(40.0, -75.0)]
    )
    assert values == pytest.approx((18.0,))
    assert selection.name == "LF2025_EVH"


def test_landfire_canopy_height_and_base_are_decoded_in_meters() -> None:
    heights, bases, layers = LandfireCanopyHeightSource(_LandfireHttp()).sample_many(
        [GeoPoint(40.0, -75.0)]
    )
    assert heights == pytest.approx((18.5,))
    assert bases == pytest.approx((5.5,))
    assert layers[0].name == "LF2025_CH"
    assert layers[1].name == "LF2025_CBH"
