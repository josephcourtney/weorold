from __future__ import annotations

from tests.fake_http import FakeHttp
from weorold import GeoPoint
from weorold.geospatial import (
    OsmRouteSurfaceSource,
)


def test_osm_surface_matcher_preserves_surface_and_trail_observations():
    def responder(_url, params):
        assert "highway" in params["data"]
        return {
            "elements": [
                {
                    "type": "way",
                    "id": 7,
                    "tags": {
                        "highway": "path",
                        "surface": "mud",
                        "sac_scale": "mountain_hiking",
                    },
                    "geometry": [
                        {"lat": 40.0, "lon": -75.0},
                        {"lat": 40.001, "lon": -75.0},
                    ],
                }
            ]
        }

    points = (
        GeoPoint(40.0, -75.0),
        GeoPoint(40.001, -75.0),
    )

    matcher = OsmRouteSurfaceSource(FakeHttp(responder)).build_matcher(points)

    match = matcher.match(GeoPoint(40.0005, -75.00005))

    assert match is not None
    assert match.surface_key == "soil"
    assert match.way_id == 7
    assert match.tags["sac_scale"] == "mountain_hiking"

    # REMOVE: assert match.terrain_factor == 1.30
