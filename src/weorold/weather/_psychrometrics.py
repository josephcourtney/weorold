from __future__ import annotations

from math import exp, isfinite

STEFAN_BOLTZMANN_W_M2_K4 = 5.670374419e-8


def saturation_vapor_pressure_pa(temp_c: float) -> float:
    """Buck-style saturation vapor pressure over liquid water."""
    if not isfinite(temp_c):
        raise ValueError("temp_c must be finite")
    return 611.21 * exp((18.678 - temp_c / 234.5) * (temp_c / (257.14 + temp_c)))


def relative_humidity_from_vapor_pressure_pct(temp_c: float, vapor_pressure_pa: float) -> float:
    if not isfinite(vapor_pressure_pa) or vapor_pressure_pa < 0:
        raise ValueError("vapor_pressure_pa must be finite and non-negative")
    return min(100.0, max(0.0, 100.0 * vapor_pressure_pa / saturation_vapor_pressure_pa(temp_c)))
