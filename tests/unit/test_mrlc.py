from __future__ import annotations

import pytest

from tests.fake_http import FakeHttp
from weorold import DataSourceError, GeoPoint
from weorold.geospatial import (
    GeoServerWmsPointSource,
    LandCoverClass,
    MrlcImperviousSource,
    MrlcLandCoverSource,
    WmsLayerSelection,
)


def test_wms_discovers_latest_year_and_extracts_gray_index():
    capabilities = b"""<?xml version='1.0'?>
    <WMT_MS_Capabilities>
      <Capability><Layer>
        <Layer queryable='1'><Name>cover_2024</Name><Title>Land Cover 2024</Title></Layer>
        <Layer queryable='1'><Name>cover_2025</Name><Title>Land Cover 2025</Title></Layer>
      </Layer></Capability>
    </WMT_MS_Capabilities>"""

    def responder(_url, params):
        if params.get("request") == "GetCapabilities":
            return capabilities
        assert params["layers"] == "cover_2025"
        return {"features": [{"properties": {"GRAY_INDEX": 42}}]}

    http = FakeHttp(responder)
    source = GeoServerWmsPointSource(
        FakeHttp(responder),
        "https://example/wms",
    )
    selected = source.resolve_layer()
    assert selected.name == "cover_2025"
    assert source.sample(GeoPoint(40, -75), selection=selected) == 42.0

    land_cover = MrlcLandCoverSource(http, service_url="https://example/wms")
    assert land_cover.sample_many([GeoPoint(40, -75)]) == (LandCoverClass.EVERGREEN_FOREST,)


def test_wms_fractional_impervious_is_normalized():
    capabilities = b"""<?xml version='1.0'?>
    <WMT_MS_Capabilities>
      <Capability><Layer>
        <Layer queryable='1'><Name>impervious_2025</Name><Title>Impervious 2025</Title></Layer>
      </Layer></Capability>
    </WMT_MS_Capabilities>"""

    def responder(_url, params):
        if params.get("request") == "GetCapabilities":
            return capabilities
        return {"features": [{"properties": {"GRAY_INDEX": 37}}]}

    source = MrlcImperviousSource(FakeHttp(responder), service_url="https://example/wms")
    assert source.sample_many([GeoPoint(40, -75)]) == (0.37,)


def test_wms_rejects_unparseable_non_json_feature_response():
    source = GeoServerWmsPointSource(
        FakeHttp(lambda _url, _params: b"upstream service returned an error page"),
        "https://example/wms",
    )

    with pytest.raises(DataSourceError, match="no parseable raster value"):
        source.sample(
            GeoPoint(40, -75),
            selection=WmsLayerSelection("cover_2025", "Land Cover 2025"),
        )
