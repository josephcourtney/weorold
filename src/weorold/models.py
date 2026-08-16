from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """A WGS84 geographic coordinate."""

    latitude_deg: float
    longitude_deg: float

    def __post_init__(self) -> None:
        if isinstance(self.latitude_deg, bool) or not isinstance(
            self.latitude_deg,
            (int, float),
        ):
            msg = "latitude_deg must be numeric"
            raise TypeError(msg)

        if isinstance(self.longitude_deg, bool) or not isinstance(
            self.longitude_deg,
            (int, float),
        ):
            msg = "longitude_deg must be numeric"
            raise TypeError(msg)

        latitude = float(self.latitude_deg)
        longitude = float(self.longitude_deg)

        if not isfinite(latitude) or not -90.0 <= latitude <= 90.0:
            msg = "latitude_deg must be finite and in [-90, 90]"
            raise ValueError(msg)

        if not isfinite(longitude) or not -180.0 <= longitude <= 180.0:
            msg = "longitude_deg must be finite and in [-180, 180]"
            raise ValueError(msg)

        object.__setattr__(
            self,
            "latitude_deg",
            latitude,
        )
        object.__setattr__(
            self,
            "longitude_deg",
            longitude,
        )
