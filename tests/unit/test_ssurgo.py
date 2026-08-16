from __future__ import annotations

import json

from weorold import DataSourceError, GeoPoint
from weorold.geospatial import (
    SsurgoSoilSource,
)


class _SsurgoHttp:
    def post(self, url, *, body, headers=None, ttl_s=None):
        del url, headers, ttl_s
        request = json.loads(body)
        assert "SDA_Get_Mukey" in request["query"]
        header = [
            "mukey",
            "muname",
            "cokey",
            "compname",
            "comppct_r",
            "hzdept_r",
            "hzdepb_r",
            "sandtotal_r",
            "claytotal_r",
            "om_r",
            "dbthirdbar_r",
            "ksat_r",
            "awc_r",
            "wthirdbar_r",
            "wfifteenbar_r",
            "wsatiated_r",
        ]
        rows = [
            ["1", "Test loam", "11", "A", 70, 0, 50, 40, 20, 3, 1.3, 10, 0.18, 30, 12, 45],
            ["1", "Test loam", "11", "A", 70, 50, 100, 35, 25, 2, 1.4, 5, 0.16, 28, 13, 43],
            ["1", "Test loam", "12", "B", 30, 0, 100, 50, 15, 1, 1.5, 20, 0.20, 32, 10, 47],
        ]
        return json.dumps({"Table": [header, *rows]}).encode()


def test_ssurgo_returns_normalized_horizon_profile() -> None:
    profile = SsurgoSoilSource(_SsurgoHttp()).sample(GeoPoint(40.0, -75.0))

    assert len(profile.horizons) == 3

    first = profile.horizons[0]
    assert first.mukey == "1"
    assert first.map_unit_name == "Test loam"
    assert first.component_key == "11"
    assert first.component_pct == 70.0
    assert first.top_cm == 0.0
    assert first.bottom_cm == 50.0
    assert first.sand_pct == 40.0
    assert first.clay_pct == 20.0
    assert first.bulk_density_g_cm3 == 1.3
    assert first.ksat_um_s == 10.0


class _FailingSsurgoHttp:
    def post(self, url, *, body, headers=None, ttl_s=None):
        del url, body, headers, ttl_s
        raise DataSourceError("upstream unavailable")


def test_ssurgo_sample_many_propagates_data_source_failures() -> None:
    source = SsurgoSoilSource(_FailingSsurgoHttp())

    try:
        source.sample_many([GeoPoint(40.0, -75.0)])
    except DataSourceError as exc:
        assert str(exc) == "upstream unavailable"
    else:
        raise AssertionError("expected DataSourceError")
