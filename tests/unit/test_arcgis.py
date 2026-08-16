from __future__ import annotations

import json

from tests.fake_http import FakeHttp
from weorold import GeoPoint
from weorold.geospatial import (
    ArcGisImageSampleSource,
)


def test_arcgis_image_sampler_preserves_multipoint_order():
    def responder(url, params):
        assert url.endswith("/getSamples")
        geometry = json.loads(params["geometry"])
        assert len(geometry["points"]) == 2
        return {
            "samples": [
                {"location": {"x": 1000, "y": 2000}, "value": "123.5"},
                {"location": {"x": 1001, "y": 2001}, "value": "130.0"},
            ]
        }

    source = ArcGisImageSampleSource(FakeHttp(responder), "https://example/ImageServer")
    a = GeoPoint(40.0, -75.0)
    b = GeoPoint(40.1, -75.1)
    values = source.sample_points([a, b])
    assert values[(40.0, -75.0)] == 123.5
    assert values[(40.1, -75.1)] == 130.0
