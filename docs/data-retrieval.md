# Remote data retrieval

`weorold.sources` is the outer adapter layer that turns public forecast and
geospatial services into the source-independent objects consumed by the simulation
core. The physical packages remain usable offline with synthetic or locally sampled
inputs.

## One-call route preparation

\`\`\`python
from datetime import datetime
from zoneinfo import ZoneInfo

from weorold.route import route_from_gpx_file
from weorold.sources import RouteRetrievalOptions, prepare_us_route_inputs

ny = ZoneInfo("America/New_York")
route = route_from_gpx_file("hike.gpx")
inputs = prepare_us_route_inputs(
    route,
    start=datetime(2026, 8, 15, 8, tzinfo=ny),
    end=datetime(2026, 8, 15, 16, tzinfo=ny),
    cache_dir=".cache/weorold",
    options=RouteRetrievalOptions(weather_provider="auto"),
)
\`\`\`

The returned `RetrievedRouteInputs` contains:

- an elevation-enriched `Route`;
- a normalized `WeatherTimeline`, including antecedent forcing when the weather
  provider can supply it;
- a `RouteContextProvider` containing land cover, canopy, route surface,
  terrain-cost, and terrain-horizon information;
- source/provenance records;
- warnings for optional sources that degraded to model priors.


### High-fidelity route context

The default route retrieval remains deliberately lightweight. The higher-fidelity
soil, moisture, vegetation-height, and lidar sources are opt-in because SMAP needs
NASA Earthdata authentication and lidar geometry needs an external PDAL executable.

```bash
uv sync --extra advanced-data
# macOS, for lidar/EPT processing:
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
    cache_dir=".cache/weorold",
    earthdata_token=os.environ["EARTHDATA_TOKEN"],
    options=HIGH_FIDELITY_ROUTE_RETRIEVAL_OPTIONS,
)
```

This adds, where data are available:

- SSURGO horizon-weighted hydraulic and soil-thermal parameters;
- SMAP L4 surface and root-zone volumetric moisture as the initial water state;
- LANDFIRE vegetation/canopy height;
- 3DEP lidar-derived canopy top/base, cover, sky view, and directional gap geometry.

All four sources feed explicit physical state. None is converted into an arbitrary
fixed air-temperature or relative-humidity offset.

It feeds directly into `compile_route_exposure`:

\`\`\`python
from weorold import ActivityRequest, TargetThermalMetPacer, compile_route_exposure
from weorold.activities import get_activity

activity = ActivityRequest(get_activity("hiking"))
pacer = TargetThermalMetPacer(target_thermal_met=5.0, body_mass_kg=75.0)
compiled = compile_route_exposure(
    weather=inputs.weather,
    route=inputs.route,
    context_provider=inputs.context_provider,
    pacer=pacer,
    activity=activity,
    start=datetime(2026, 8, 15, 8, tzinfo=ny),
)
\`\`\`

## Weather

### Open-Meteo

The default `auto` policy first requests Open-Meteo because the exposure model
needs radiation components that are not available in the NWS raw grid API. The
adapter requests, at hourly resolution:

- 2 m air temperature;
- 2 m relative humidity;
- surface pressure;
- 10 m wind speed and direction;
- total cloud cover;
- precipitation;
- instantaneous direct-normal irradiance (DNI);
- instantaneous diffuse-horizontal irradiance (DHI).

The route's 3DEP-derived representative elevation is sent to Open-Meteo so its
statistical elevation downscaling is referenced to the route rather than only the
provider's default terrain grid.

The default request includes 12 hours of antecedent forcing. The route
microclimate evaluator uses those earlier temperature, radiation, wind, humidity,
and precipitation values to spin up surface heat and water state before the person
enters a route zone.

Endpoint:

\`\`\`text
https://api.open-meteo.com/v1/forecast
\`\`\`

### National Weather Service

`weather_provider="nws"` uses the official NWS API directly. `auto` also falls
back to it when Open-Meteo retrieval fails. The adapter resolves
`/points/{lat},{lon}` to `forecastGridData` and normalizes the raw grid series.

NWS raw grid data does not expose the DNI/DHI forcing required by the thermal
radiation model, so this adapter calculates a deliberately labeled planning-scale
solar estimate from solar geometry and NWS sky cover. It also cannot supply the
same antecedent forecast history through this path, so microclimate spin-up starts
at the requested route interval. Those limitations are emitted as warnings and in
source provenance.

Endpoint:

\`\`\`text
https://api.weather.gov
\`\`\`

## Elevation and terrain shade

The USGS 3DEP ImageServer is sampled with ArcGIS `getSamples` multipoint requests.
The retrieval layer batches points, preserves route order, and exposes the result as
an ordinary callable elevation field.

3DEP elevation is used for:

- route elevation enrichment;
- smoothed grade and ascent/descent;
- grade-dependent locomotion energetics;
- representative route elevation for the weather request;
- terrain-horizon ray marching and terrain shade.

Terrain horizons are sampled less densely along the route than walking grade. For
each horizon anchor, radial elevation probes are generated by azimuth and distance,
then converted to a `HorizonProfile`. The simulation evaluates that profile against
the actual solar azimuth/elevation at traversal time.

Endpoint:

\`\`\`text
https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer
\`\`\`

## Land cover, tree canopy, and impervious surface

MRLC datasets are consumed through their published OGC WMS services. The adapter
uses `GetCapabilities` to discover the newest layer/year exposed by a service and
records that resolved layer in provenance before requesting point values with
`GetFeatureInfo`.

The route preparation pipeline currently uses:

- Annual NLCD Land Cover -> `LandCover` and surface/microclimate priors;
- NLCD Tree Canopy Cover -> local canopy fraction, which in turn determines
  fallback LAI, direct-beam attenuation, and canopy wind attenuation;
- Annual NLCD Fractional Impervious Surface -> distinguishes predominantly
  vegetated developed-open-space from hard developed surfaces when OpenStreetMap
  does not identify the actual travel surface.

Current CONUS service endpoints are represented as constants in
`weorold.sources.geospatial.mrlc`; callers may override service URLs or pin layer
names for reproducible archived runs.


## Soil hydraulic properties and moisture state

### SSURGO / Soil Data Access

`SsurgoSoilSource` queries USDA NRCS Soil Data Access through `post.rest`. For the
map unit at each route sample it combines major-component horizons over the upper
one metre, weighting by component percentage and horizon thickness. The retrieved
properties are normalized into `SoilHydraulicProperties`:

- water content near field capacity (`wthirdbar_r`);
- wilting-point water content (`wfifteenbar_r`);
- satiated water content / porosity (`wsatiated_r`);
- saturated hydraulic conductivity (`ksat_r`);
- bulk density (`dbthirdbar_r`);
- sand, clay, and organic-matter fractions.

These parameters drive the two-layer `SoilHydrologyModel`, rather than merely
labeling soil type. The model represents a fast surface layer and slower root zone,
conserves liquid water, limits infiltration by conductivity/pore space, moves water
downward toward field capacity, drains the root zone, and limits evaporation/
evapotranspiration at wilting point. Soil moisture also changes the effective
volumetric heat capacity and thermal conductivity used by `SurfaceEnergyModel`.

Endpoint:

```text
https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest
```

### SMAP L4 moisture assimilation

`SmapL4Source` selects NASA `SPL4SMGP` Version 8 through CMR and reads the nearest
9 km EASE-Grid surface/root-zone soil-moisture state from the selected HDF5 granule.
The route microclimate first spins up its thermal state from antecedent weather, then
assimilates the SMAP observation at route start. This avoids incorrectly applying a
future/current moisture observation at the beginning of the spin-up interval.

SMAP is coarse relative to a trail, so it initializes water state; SSURGO provides
the local hydraulic thresholds and texture. If SMAP is present where SSURGO has a
coverage hole, an explicitly labeled generic-loam parameter set is used rather than
discarding the observed moisture.

SMAP access requires a NASA Earthdata bearer token (`EARTHDATA_TOKEN`) plus the
`advanced-data` extra (`h5py`, `pyproj`). The current adapter downloads the selected
HDF5 granule and samples it locally; a future optimization can replace that transfer
with NASA Harmony spatial subsetting without changing the model interface.

## Vegetation height and canopy geometry

### LANDFIRE

The LANDFIRE adapter consumes three height products:

- Existing Vegetation Height (EVH), decoded to representative tree/shrub/herb height;
- Forest Canopy Height (CH), the overstory canopy top;
- Forest Canopy Base Height (CBH), the lower canopy boundary.

EVH supplies low-vegetation roughness when the pedestrian is not under an overstory.
CH/CBH supply a vertically explicit crown for canopy wind attenuation. NLCD canopy
cover is retained as the plan-view cover estimate when lidar is unavailable.

As of August 2026, LF2025 vegetation is only published for released GeoAreas rather
than full CONUS. Retrieval therefore uses LF2025 first and fills missing route cells
from the completed LF2024 CONUS products. Both actual service/version selections are
recorded in source provenance.

### 3DEP lidar canopy geometry

Where a 3DEP lidar point-cloud project intersects the route, `PdalEptCanopySource`
uses the public EPT hierarchy and a bounded PDAL `readers.ept` query around the route
point. Ground returns establish local ground elevation; vegetation returns produce:

- p95 canopy top height;
- lower-crown/base height;
- plan-view canopy cover from occupied cells;
- an azimuth/elevation `CanopyGapGrid`;
- hemispheric sky-view fraction.

The exposure compiler evaluates the directional gap grid using the actual solar
azimuth/elevation for that time and route position. Lidar geometry therefore
overrides the Beer-Lambert LAI fallback for direct-beam shade. The same top/base
geometry also controls how much LAI lies above pedestrian height for the canopy wind
attenuation model.

The directional gap estimator is intentionally a reduced geometric model: point
returns in an angular bin are converted to a gap probability and are not claimed to
be a calibrated leaf-angle/radiative-transfer inversion.

PDAL is optional so the rest of `weorold` remains installable without a point-cloud
stack. Missing PDAL or absent 3DEP point-cloud coverage degrades to LANDFIRE/NLCD
canopy information unless strict source mode is enabled.

## OpenStreetMap route surface

The Overpass adapter downloads nearby `highway=*` ways with geometry and associates
route locations with the nearest way inside a configurable match radius. It uses
OSM's descriptive tags such as:

- `surface=*` for pavement, gravel, soil, mud, sand, rock, etc.;
- `sac_scale=*` for hiking difficulty;
- `tracktype=*` for track quality.

The physical surface tag selects the route surface model. Difficulty/track tags are
mapped to explicit *project heuristics* for the locomotion terrain multiplier; the
multipliers are not values supplied by OpenStreetMap and are kept in one table in
`osm.py` so they can later be calibrated or replaced.

Default endpoint:

\`\`\`text
https://overpass-api.de/api/interpreter
\`\`\`

## Failure policy

Weather and elevation are mandatory because route timing and the thermal boundary
cannot be constructed sensibly without them.

Land cover, canopy, imperviousness, OpenStreetMap surface observations, terrain
horizons, SSURGO, SMAP, LANDFIRE height, and lidar geometry are optional context
sources. The four high-fidelity sources are disabled by the default options and
enabled together by `HIGH_FIDELITY_ROUTE_RETRIEVAL_OPTIONS`. An unavailable optional
source produces a warning and retains the next-best physical/prior input. Use
`strict_context_sources=True` when reproducibility or validation requires every
requested source to succeed.

`weather_provider="auto"` is the only cross-provider fallback: it attempts
Open-Meteo first and then NWS. `open_meteo` and `nws` modes fail rather than silently
changing provider.

## Cache and request behavior

`CachedHttpClient` uses only the Python standard library. It provides:

- deterministic URL/query encoding;
- a configurable User-Agent;
- timeouts;
- retry/backoff for transient network errors and HTTP 429/5xx responses;
- optional SHA-256-addressed on-disk response caching;
- atomic cache writes.

Source adapters choose independent freshness windows: weather is short-lived,
OpenStreetMap is cached longer, and static raster service responses are cached for
weeks. Passing a custom `HttpGetter` makes every source deterministic in tests and
allows applications to substitute an asynchronous downloader, organization proxy,
or offline cache without changing model code.

## Deliberate boundaries

External data are still promoted only when a physical consumer exists. SSURGO, SMAP,
LANDFIRE height, and lidar canopy geometry are now in the one-call high-fidelity
pipeline because soil water/thermal dynamics, vegetation wind attenuation, and
directional canopy-radiation models consume them directly.

Important remaining boundaries include:

- building footprints/heights and urban canyon ray tracing;
- snowpack state and snow-specific surface/locomotion physics;
- hydrologic routing/stream temperature beyond the local two-layer soil bucket;
- forecast ensembles and propagated uncertainty;
- site calibration of soil/canopy reduced-order coefficients.

The national products also have different native scales. In particular, SMAP's 9 km
moisture state should be interpreted as a regional initial condition, not a claim to
measure the exact moisture of a trail tread. Lidar can be much more spatially
specific, but its directional gap conversion remains model-derived rather than a
direct hemispherical-transmittance measurement.
