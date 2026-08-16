from __future__ import annotations

import csv
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from weorold._transport import HttpGetter
from weorold.errors import DataSourceError
from weorold.geospatial.models import LidarPoint
from weorold.models import GeoPoint

USGS_3DEP_LIDAR_INDEX_URL = (
    "https://index.nationalmap.gov/arcgis/rest/services/3DEPElevationIndex/MapServer/8/query"
)
USGS_LIDAR_PUBLIC_ROOT = "https://s3-us-west-2.amazonaws.com/usgs-lidar-public"


@dataclass(frozen=True, slots=True)
class LidarProject:
    workunit: str
    project: str
    quality_level: str | None
    ept_url: str


@dataclass(frozen=True, slots=True)
class UsgsLidarProjectSource:
    http: HttpGetter
    index_url: str = USGS_3DEP_LIDAR_INDEX_URL
    cache_ttl_s: float = 30 * 24 * 3600.0

    def locate(self, point: GeoPoint) -> LidarProject | None:
        raw = self.http.get(
            self.index_url,
            params={
                "f": "json",
                "geometry": f"{point.longitude_deg},{point.latitude_deg}",
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "workunit,project,ql,lpc_pub_date",
                "returnGeometry": "false",
                "orderByFields": "lpc_pub_date DESC",
            },
            ttl_s=self.cache_ttl_s,
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DataSourceError("3DEP lidar index returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise DataSourceError("3DEP lidar index response is not an object")
        if "error" in payload:
            raise DataSourceError(f"3DEP lidar index error: {payload['error']}")
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            return None
        attrs = features[0].get("attributes") if isinstance(features[0], dict) else None
        if not isinstance(attrs, dict):
            return None
        workunit = attrs.get("workunit")
        if not isinstance(workunit, str) or not workunit.strip():
            return None
        workunit = workunit.strip()
        project = attrs.get("project")
        project_name = project.strip() if isinstance(project, str) and project.strip() else workunit
        ql = attrs.get("ql")
        quality = ql.strip() if isinstance(ql, str) and ql.strip() else None
        return LidarProject(
            workunit=workunit,
            project=project_name,
            quality_level=quality,
            ept_url=f"{USGS_LIDAR_PUBLIC_ROOT}/{workunit}/ept.json",
        )


def _ept_crs(payload: object) -> object:
    if not isinstance(payload, dict):
        raise DataSourceError("EPT metadata is not an object")
    srs = payload.get("srs")
    if not isinstance(srs, dict):
        raise DataSourceError("EPT metadata contains no spatial reference")
    wkt = srs.get("wkt")
    if isinstance(wkt, str) and wkt.strip():
        return wkt
    authority = srs.get("authority")
    horizontal = srs.get("horizontal")
    if isinstance(authority, str) and horizontal is not None:
        return f"{authority}:{horizontal}"
    raise DataSourceError("EPT spatial reference cannot be interpreted")


@dataclass(frozen=True, slots=True)
class PdalEptPointSource:
    """Retrieve locally projected classified points from public USGS 3DEP EPT lidar.

    PDAL is invoked as an optional system dependency because its EPT reader can
    spatially query the cloud-hosted point hierarchy without downloading a whole
    lidar project. The Python package therefore remains usable without PDAL.
    """

    http: HttpGetter
    project_source: UsgsLidarProjectSource | None = None
    pdal_executable: str = "pdal"
    radius_m: float = 30.0
    ept_resolution_m: float = 0.75
    cache_ttl_s: float = 30 * 24 * 3600.0

    def __post_init__(self) -> None:
        if self.radius_m <= 0 or self.ept_resolution_m <= 0:
            raise ValueError("lidar radius and EPT resolution must be positive")

    @property
    def available(self) -> bool:
        return shutil.which(self.pdal_executable) is not None

    def _project_source(self) -> UsgsLidarProjectSource:
        return self.project_source or UsgsLidarProjectSource(self.http)

    def _metadata(self, project: LidarProject) -> dict[str, Any]:
        try:
            payload = json.loads(self.http.get(project.ept_url, ttl_s=self.cache_ttl_s))
        except json.JSONDecodeError as exc:
            raise DataSourceError(f"invalid EPT metadata for {project.workunit}") from exc
        if not isinstance(payload, dict):
            raise DataSourceError("EPT metadata is not an object")
        return payload

    def _source_xy(
        self,
        point: GeoPoint,
        metadata: dict[str, Any],
    ) -> tuple[float, float, float, float]:
        try:
            from pyproj import CRS, Transformer  # noqa PLC0415 # no cover - optional dependency
        except ImportError as exc:
            raise DataSourceError("3DEP EPT point retrieval requires pyproj") from exc
        target = CRS.from_user_input(_ept_crs(metadata))
        if not target.is_projected:
            raise DataSourceError(
                "3DEP EPT source CRS must be projected for meter-radius canopy sampling"
            )
        axis = target.axis_info[0] if target.axis_info else None
        meters_per_unit = None if axis is None else axis.unit_conversion_factor
        if meters_per_unit is None or meters_per_unit <= 0:
            raise DataSourceError("EPT projected CRS has no usable linear-unit conversion")
        vertical_axis = target.axis_info[2] if len(target.axis_info) >= 3 else axis
        vertical_meters_per_unit = (
            None if vertical_axis is None else vertical_axis.unit_conversion_factor
        )
        if vertical_meters_per_unit is None or vertical_meters_per_unit <= 0:
            vertical_meters_per_unit = meters_per_unit
        transformer = Transformer.from_crs("EPSG:4326", target, always_xy=True)
        x, y = transformer.transform(point.longitude_deg, point.latitude_deg)
        return (
            float(x),
            float(y),
            float(meters_per_unit),
            float(vertical_meters_per_unit),
        )

    def _read_points(
        self,
        *,
        project: LidarProject,
        x: float,
        y: float,
        meters_per_unit: float,
        vertical_meters_per_unit: float,
    ) -> list[LidarPoint]:
        if not self.available:
            raise DataSourceError("PDAL executable is not available for 3DEP EPT canopy sampling")
        radius = self.radius_m / meters_per_unit
        bounds = f"([{x - radius},{x + radius}],[{y - radius},{y + radius}])"
        with TemporaryDirectory(prefix="weorold-lidar-") as directory:
            output = Path(directory) / "points.csv"
            pipeline = {
                "pipeline": [
                    {
                        "type": "readers.ept",
                        "filename": project.ept_url,
                        "bounds": bounds,
                        "resolution": self.ept_resolution_m / meters_per_unit,
                    },
                    {
                        "type": "writers.text",
                        "filename": str(output),
                        "format": "csv",
                        "order": "X,Y,Z,Classification",
                        "keep_unspecified": False,
                    },
                ]
            }
            process = subprocess.run(
                [self.pdal_executable, "pipeline", "--stdin"],
                input=json.dumps(pipeline),
                text=True,
                capture_output=True,
                check=False,
            )
            if process.returncode != 0:
                detail = (process.stderr or process.stdout).strip()
                raise DataSourceError(f"PDAL EPT query failed: {detail[:500]}")
            points: list[LidarPoint] = []
            with output.open(newline="") as stream:
                for row in csv.DictReader(stream):
                    try:
                        classification = row.get("Classification")
                        points.append(
                            LidarPoint(
                                x_m=(float(row["X"]) - x) * meters_per_unit,
                                y_m=(float(row["Y"]) - y) * meters_per_unit,
                                elevation_m=float(row["Z"]) * vertical_meters_per_unit,
                                classification=(
                                    None
                                    if classification in {None, ""}
                                    else int(float(classification))
                                ),
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
            return points

    def sample(
        self,
        point: GeoPoint,
    ) -> tuple[LidarPoint, ...] | None:
        project = self._project_source().locate(point)
        if project is None:
            return None

        metadata = self._metadata(project)
        x, y, meters_per_unit, vertical_meters_per_unit = self._source_xy(
            point,
            metadata,
        )

        return tuple(
            self._read_points(
                project=project,
                x=x,
                y=y,
                meters_per_unit=meters_per_unit,
                vertical_meters_per_unit=vertical_meters_per_unit,
            )
        )

    def sample_many(
        self,
        points: list[GeoPoint],
    ) -> tuple[tuple[LidarPoint, ...] | None, ...]:
        return tuple(self.sample(point) for point in points)
