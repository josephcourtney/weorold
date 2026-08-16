from __future__ import annotations

import json

from weorold import GeoPoint
from weorold.geospatial import (
    UsgsLidarProjectSource,
)


class _LidarIndexHttp:
    def get(self, url, *, params=None, headers=None, ttl_s=None):
        del url, headers, ttl_s
        assert isinstance(params, dict)
        assert params["outFields"].startswith("workunit")
        return json.dumps(
            {
                "features": [
                    {
                        "attributes": {
                            "workunit": "PA_Test_2024",
                            "project": "Test Project",
                            "ql": "QL2",
                            "lpc_pub_date": 1,
                        }
                    }
                ]
            }
        ).encode()


def test_3dep_lidar_index_resolves_public_ept_project() -> None:
    project = UsgsLidarProjectSource(_LidarIndexHttp()).locate(GeoPoint(40.0, -75.0))
    assert project is not None
    assert project.workunit == "PA_Test_2024"
    assert project.quality_level == "QL2"
    assert project.ept_url.endswith("/PA_Test_2024/ept.json")
