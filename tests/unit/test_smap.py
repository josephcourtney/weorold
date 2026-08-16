from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from typing import cast

import h5py
import numpy as np
import pytest

from weorold import GeoPoint
from weorold._transport import HttpGetter
from weorold.geospatial import (
    SmapL4Source,
)


def _smap_hdf_bytes() -> bytes:
    stream = BytesIO()
    with h5py.File(stream, "w") as handle:
        geo = handle.create_group("Geolocation_Data")
        geo.create_dataset("cell_lat", data=np.array([[40.0, 40.0], [41.0, 41.0]]))
        geo.create_dataset("cell_lon", data=np.array([[-75.0, -74.0], [-75.0, -74.0]]))
        data = handle.create_group("Analysis_Data")
        surface = data.create_dataset("sm_surface", data=np.array([[0.21, 0.22], [0.31, 0.32]]))
        root = data.create_dataset("sm_rootzone", data=np.array([[0.29, 0.30], [0.39, 0.40]]))
        surface.attrs["_FillValue"] = -9999.0
        root.attrs["_FillValue"] = -9999.0
    return stream.getvalue()


class _SmapHttp:
    def __init__(self) -> None:
        self.hdf = _smap_hdf_bytes()

    def get(self, url, *, params: dict | None = None, headers=None, ttl_s=None):
        del ttl_s
        if "cmr.earthdata" in url:
            assert isinstance(params, dict)
            assert params["short_name"] == "SPL4SMGP"
            return json.dumps(
                {
                    "feed": {
                        "entry": [
                            {
                                "producer_granule_id": "SMAP_TEST",
                                "time_start": "2026-08-15T21:00:00Z",
                                "links": [
                                    {
                                        "href": "https://earthdata.test/SMAP_TEST.h5",
                                        "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                                    }
                                ],
                            }
                        ]
                    }
                }
            ).encode()
        assert headers == {"Authorization": "Bearer token"}
        return self.hdf


def test_smap_l4_initializes_surface_and_rootzone_vwc() -> None:
    sample = SmapL4Source(cast("HttpGetter", _SmapHttp()), earthdata_token="token").sample_many(
        [GeoPoint(40.1, -74.9), GeoPoint(40.9, -74.1)],
        when=datetime(2026, 8, 15, 22, tzinfo=UTC),
    )
    assert sample[0] is not None and sample[1] is not None

    assert sample[0].surface_vwc == pytest.approx(0.21)
    assert sample[0].root_zone_vwc == pytest.approx(0.29)

    assert sample[1].surface_vwc == pytest.approx(0.32)
    assert sample[1].granule_id == "SMAP_TEST"
