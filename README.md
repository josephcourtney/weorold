# weorold

Stateful thermal-activity planning primitives built around JOS-3, dynamic garments,
semantic activities, outdoor microenvironments, hydration accounting, and trajectory
assessment.

## Architecture

\`\`\`text
debug | sources
      |
 assessment
      |
simulation | exposure | hydration
      |
  locomotion
      |
activities | environment | gear | physiology | route
      |
    domain
\`\`\`

The layers are intentionally separated:

- `domain/`: canonical body-region, range, and thermal-exposure primitives.
- `activities/`: semantic activity catalog and phased MET/movement profiles.
- `environment/`: forecast timeline, solar geometry, and microenvironment transforms.
- `exposure/`: compiles weather + place + activity into time-varying `ThermalExposure`.
- `physiology/`: stateful JOS-3 adapter and normalized physiology output.
- `gear/`: dynamic garment temperature/water state and multilayer coupling.
- `simulation/`: trajectory orchestration for physiology and garments.
- `hydration/`: body-water loss and explicit drinking state.
- `assessment/`: transparent planning-oriented comfort/strain reductions.
- `route/` and `locomotion/`: route geometry, terrain situations, pacing, and
  mechanistic route workload.
- `sources/`: network/cache adapters that retrieve model-ready weather, 3DEP
  elevation/lidar, NLCD/LANDFIRE vegetation, SSURGO soil, SMAP moisture, and
  OpenStreetMap route observations.

## Semantic activity -> outdoor exposure

\`\`\`python
from datetime import datetime
from zoneinfo import ZoneInfo

from weorold import ActivityRequest, Location, WeatherPoint, WeatherTimeline
from weorold.activities import get_activity
from weorold.environment import FOREST
from weorold.exposure import compile_activity_exposure

ny = ZoneInfo("America/New_York")
weather = WeatherTimeline(
    (
        WeatherPoint(
            datetime(2026, 8, 14, 7, tzinfo=ny),
            air_temp_c=22,
            relative_humidity_pct=70,
            wind_speed_m_s=2.0,
            direct_normal_solar_w_m2=350,
            diffuse_horizontal_solar_w_m2=90,
        ),
        WeatherPoint(
            datetime(2026, 8, 14, 11, tzinfo=ny),
            air_temp_c=29,
            relative_humidity_pct=60,
            wind_speed_m_s=3.0,
            direct_normal_solar_w_m2=800,
            diffuse_horizontal_solar_w_m2=120,
        ),
    )
)

compiled = compile_activity_exposure(
    weather=weather,
    location=Location(40.7128, -74.0060),
    microenvironment=FOREST,
    activity=ActivityRequest(get_activity("hiking"), duration_s=2 * 3600),
    start=datetime(2026, 8, 14, 8, tzinfo=ny),
)
\`\`\`

`compiled.exposures` can be fed directly to `JOS3Simulator`, or to the dynamic
`GarmentCoupledSimulator` when clothing is modeled explicitly.


## High-fidelity route environment

The default route retrieval remains lightweight. For the physical soil/canopy data
path, install the optional Python dependencies and enable the high-fidelity preset:

```bash
uv sync --extra advanced-data
# Optional but required for 3DEP point-cloud canopy geometry:
brew install pdal
```

```python
import os
from weorold.sources import (
    HIGH_FIDELITY_ROUTE_RETRIEVAL_OPTIONS,
    prepare_us_route_inputs,
)

inputs = prepare_us_route_inputs(
    route,
    start=start,
    end=end,
    earthdata_token=os.environ["EARTHDATA_TOKEN"],
    options=HIGH_FIDELITY_ROUTE_RETRIEVAL_OPTIONS,
)
```

This combines SSURGO hydraulic properties with SMAP surface/root-zone moisture,
LANDFIRE vegetation/canopy height, and—where 3DEP point clouds and PDAL are
available—directional lidar canopy geometry. Those fields drive soil water/thermal
dynamics, canopy/roughness wind attenuation, sky view, and time-dependent direct
solar transmission. See `docs/data-retrieval.md` for source/fallback details.

## Stateful JOS-3

\`\`\`python
from weorold import JOS3Simulator

result = JOS3Simulator(step_s=60).run(compiled.exposures)
print(result.peak_core_temp_c)
print(result.estimated_sweat_secretion_g)
print(result.estimated_body_water_loss_g)
\`\`\`

### Improved sweat/liquid-water interface

JOS-3 calculates a regulatory sweating signal before skin wettedness is capped,
but its public `e_sweat` output is the *effective evaporated* sweating after that
cap. Gecweme reconstructs the pre-cap regulatory signal immediately before each
JOS-3 time step using the same control-law coefficients used by pythermalcomfort.

Each `JOS3Sample` therefore distinguishes:

- `sweat_evaporation_w`: sweat that can evaporate;
- `sweat_secretion_potential_w`: uncapped thermoregulatory sweat demand;
- `estimated_sweat_secretion_g_s`: estimated body-water loss through sweating;
- `estimated_non_sweat_water_loss_g_s`: skin diffusion + respiratory loss;
- `estimated_body_water_loss_g_s`: their sum.

When a nonstandard backend does not expose the required JOS-3 state, the adapter
falls back conservatively to effective evaporated sweat and labels the sample
`effective-evaporation-fallback`.

The garment model captures `secreted - evaporated` liquid sweat when the direct
JOS-3 control estimate is available; its older wettedness-based proxy is retained
only as a backend fallback.

## Dynamic garments

Garments retain two reduced-order states:

\`\`\`text
T_g(t)  garment temperature
W_g(t)  retained liquid water
\`\`\`

Wetness changes sensible insulation and evaporative resistance. Existing water can
dry; liquid sweat can enter the innermost covered layer and transfer outward through
an ensemble. Garment thermal storage is coupled back into local JOS-3 skin nodes.

The parameters are designed to be fitted from garment-level measurements rather
than interpreted as microscopic textile constants.

## Hydration

\`\`\`python
from weorold.hydration import DrinkEvent, simulate_hydration

hydration = simulate_hydration(
    result,
    drinks=[DrinkEvent(elapsed_s=3600, amount_ml=500)],
)

print(hydration.total_body_water_loss_g)
print(hydration.final_net_deficit_g)
print(hydration.peak_deficit_pct_body_mass)
\`\`\`

This is deliberately a planner-level water balance, not renal/electrolyte
physiology. It tracks estimated sweat + insensible/respiratory loss and explicit
water intake.

## Assessment

\`\`\`python
from weorold.assessment import assess_trajectory

assessment = assess_trajectory(result)
print(assessment.suitability)
print(assessment.tendency)
print(assessment.discomfort_score)
print(assessment.strain_score)
print(assessment.drivers)
\`\`\`

The scalar `discomfort_score` and `strain_score` are transparent planning heuristics,
not clinical safety indices. The raw JOS-3 state remains available for scientific
interpretation. The assessment layer exists to rank many candidate trajectories
consistently before a future scheduler/Pareto optimizer is added.

## Environment model

The current microenvironment catalog includes:

- open sun;
- open shade;
- forest canopy;
- deep shade;
- residential street.

Microenvironments transform forecast air temperature, humidity, wind, direct and
diffuse solar radiation, sky view, ground reflectance, and a long-wave radiant
offset. Solar geometry is computed from timestamp and latitude/longitude. Absorbed
short-wave radiation is converted to an equivalent MRT increment before compiling a
JOS-3 exposure.

The presets are reduced-order planning assumptions. They should eventually be
replaced or conditioned by route geometry, canopy/building data, and measured local
microclimates where available.

## Tests

The backend-independent suite covers:

- JOS-3 state carry-over;
- dynamic garment heat/moisture coupling;
- direct vs fallback sweat-liquid interfaces;
- domain primitives;
- activity catalog and phase resolution;
- weather interpolation and solar/microenvironment effects;
- semantic exposure compilation;
- hydration accounting;
- trajectory assessment;
- remote-source normalization, caching/retry behavior, WMS/ArcGIS/OSM parsing, and
  route-input orchestration with deterministic fake services.

`tests/test_integration_pythermalcomfort.py` additionally contains real-backend tests
for the garment-coupled JOS-3 path, including the `_iclo` and `_set_ex_q` compatibility
hooks used by pythermalcomfort 4.4.x. These tests run whenever `pythermalcomfort` is
installed.

## Route-aware physiological and microclimate models

The current package also includes route/situation compilation and stateful environmental
submodels. A route can be resampled and annotated with elevation, grade, bearing, land cover,
canopy, sky view, terrain horizon, surface state, and local wind modifiers. Fixed-speed or
target-thermal-MET pacing then determines traversal timing and workload, while the dynamic
microclimate carries local air, surface temperature, moisture, long-wave radiation, and shade
state through time.

See:

- `docs/physiology-microclimate.md`
- `docs/route-situations.md`
- `docs/debug-view.md`

The geospatial core still uses sampler/provider interfaces, but the outer `sources/` layer now
implements production adapters for Open-Meteo/NWS weather, USGS 3DEP elevation, MRLC Annual
NLCD land cover/tree canopy/fractional imperviousness, and OpenStreetMap trail surfaces. See
`docs/data-retrieval.md` for the one-call route preparation API, caching, provenance, and
fallback behavior.

## Debug view

Run:

\`\`\`sh
uv run weorold-debug
\`\`\`

or:

\`\`\`sh
uv run weorold debug
\`\`\`

The debug view provides linked trajectory navigation, semantic phase bands, regional JOS-3
body-state overlays, garment coverage/state inspection, hydration and workload trajectories,
and serialized route/microclimate diagnostics.
