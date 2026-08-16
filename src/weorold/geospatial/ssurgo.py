from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from weorold._transport import HttpPoster
from weorold.errors import DataSourceError
from weorold.geospatial.models import (
    SsurgoHorizon,
    SsurgoProfile,
)
from weorold.models import GeoPoint

SOIL_DATA_ACCESS_POST_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"

_COLUMNS = (
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
)


def _horizon_from_row(
    row: dict[str, object],
) -> SsurgoHorizon:
    return SsurgoHorizon(
        mukey=str(row.get("mukey", "")),
        map_unit_name=str(row.get("muname", "")),
        component_key=str(row.get("cokey", "")),
        component_name=str(row.get("compname", "")),
        component_pct=_float(row.get("comppct_r")),
        top_cm=_float(row.get("hzdept_r")),
        bottom_cm=_float(row.get("hzdepb_r")),
        sand_pct=_float(row.get("sandtotal_r")),
        clay_pct=_float(row.get("claytotal_r")),
        organic_matter_pct=_float(row.get("om_r")),
        bulk_density_g_cm3=_float(row.get("dbthirdbar_r")),
        ksat_um_s=_float(row.get("ksat_r")),
        available_water_capacity=_float(row.get("awc_r")),
        field_capacity_pct=_float(row.get("wthirdbar_r")),
        wilting_point_pct=_float(row.get("wfifteenbar_r")),
        saturation_pct=_float(row.get("wsatiated_r")),
    )


def _sql_for_point(point: GeoPoint) -> str:
    wkt = f"POINT({point.longitude_deg:.8f} {point.latitude_deg:.8f})"
    columns = ", ".join(
        f"ch.{name}"
        if name not in {"mukey", "muname", "cokey", "compname", "comppct_r"}
        else {
            "mukey": "mu.mukey",
            "muname": "mu.muname",
            "cokey": "co.cokey",
            "compname": "co.compname",
            "comppct_r": "co.comppct_r",
        }[name]
        for name in _COLUMNS
    )
    return f"""
SELECT {columns}
FROM mapunit AS mu
INNER JOIN component AS co ON co.mukey = mu.mukey
INNER JOIN chorizon AS ch ON ch.cokey = co.cokey
WHERE mu.mukey IN (
    SELECT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')
)
  AND co.majcompflag = 'Yes'
  AND ch.hzdept_r < 100
ORDER BY co.comppct_r DESC, ch.hzdept_r
""".strip()


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def _rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise DataSourceError("Soil Data Access response is not an object")
    raw = payload.get("Table")
    if not isinstance(raw, list) or not raw:
        raise DataSourceError("Soil Data Access returned no horizon rows")
    if all(isinstance(row, dict) for row in raw):
        return [cast(dict[str, object], row) for row in raw]
    if not all(isinstance(row, list) for row in raw):
        raise DataSourceError("unexpected Soil Data Access table representation")
    table = cast(list[list[object]], raw)
    header = tuple(str(value).lower() for value in table[0])
    if set(_COLUMNS).issubset(header):
        names = header
        data = table[1:]
    elif len(table[0]) == len(_COLUMNS):
        names = _COLUMNS
        data = table
    else:
        raise DataSourceError("Soil Data Access table columns do not match requested schema")
    return [dict(zip(names, row, strict=False)) for row in data]


@dataclass(frozen=True, slots=True)
class SsurgoSoilSource:
    http: HttpPoster
    endpoint: str = SOIL_DATA_ACCESS_POST_URL
    cache_ttl_s: float = 30 * 24 * 3600.0

    def sample(
        self,
        point: GeoPoint,
    ) -> SsurgoProfile:
        request = json.dumps(
            {
                "query": _sql_for_point(point),
                "format": "JSON",
            }
        ).encode("utf-8")

        raw = self.http.post(
            self.endpoint,
            body=request,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            ttl_s=self.cache_ttl_s,
        )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = "Soil Data Access returned invalid JSON"
            raise DataSourceError(msg) from exc

        rows = _rows(payload)

        return SsurgoProfile(horizons=tuple(_horizon_from_row(row) for row in rows))

    def sample_many(
        self,
        points: list[GeoPoint],
    ) -> tuple[SsurgoProfile, ...]:
        return tuple(self.sample(point) for point in points)
