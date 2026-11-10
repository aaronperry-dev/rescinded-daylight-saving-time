# rescinded-daylight-saving-time

A Python pipeline that builds an interactive **swipe map** of the contiguous U.S. showing what
changes on the clock if Daylight Saving Time is rescinded.

Drag the divider to compare two scenarios on a pan-and-zoomable **terrain and bathymetry basemap that the
pipeline renders itself** (no tile server, no API key): land is coloured by elevation in feet, the ocean and
lakes by depth in feet, with international borders, state lines and time-zone borders drawn heavily on top.

| Layer | What it shows |
|---|---|
| **Time zones** | Every legal CONUS time zone, coloured by UTC offset on a chosen date (slider across the DST period). |
| **Sunrise** | Latest / earliest sunrise of the year, as 30-minute colour bands with labelled isochrones. |
| **Sunset** | Latest / earliest sunset of the year, same style. |

Scenarios you can put on either side:

* **Current law** – today's DST rules (2nd Sunday of March to 1st Sunday of November).
* **DST rescinded** – every zone stays on standard time all year (Arizona already does).
* **Permanent DST** – clocks stay on summer time all year. Not what the repo is named for, but it is the
  case most "latest sunrise" maps show, and it makes the sunrise comparison meaningful.

A city table beside the map gives the same numbers for ten reference cities.

![swipe map: latest sunset, current vs rescinded](docs/img/sunset_latest.png)

## Quick start

```bash
git clone https://github.com/aaronperry-dev/rescinded-daylight-saving-time.git
cd rescinded-daylight-saving-time
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

rdst all                 # fetch -> process -> basemap -> solar -> build   (a few minutes; ~150 MB download)
python -m http.server -d site 8000   # then open http://localhost:8000
```

`site/index.html` also works opened straight from disk, and needs no network at all unless you pick the
optional OpenStreetMap / Esri basemaps.
`make site`, `make serve`, `make test` and `make clean` are provided as shortcuts.

## Pipeline

Each stage reads the previous stage's files from `data/`, so any one can be re-run alone.

| Command | Reads | Writes | What happens |
|---|---|---|---|
| `rdst fetch` | the internet | `data/raw/` | Downloads [Timezone Boundary Builder](https://github.com/evansiroky/timezone-boundary-builder) (legal zone polygons), the Natural Earth 10 m states, state lines, country boundary lines, ocean and lakes, and an elevation/bathymetry grid (see *Basemap*). Records URL, SHA-256 and release tag in `manifest.json`. Cached; `--force` refreshes, `--tz-release 2026f` pins a release, `--no-dem` skips the grid. |
| `rdst process` | `data/raw/` | `data/processed/conus_zones.geojson`, `boundaries.geojson`, `state_labels.json`, `zone_rules.csv` | Streams the 170 MB boundary file (≈70 MB RAM), keeps zones that `zone.tab` assigns to the U.S., clips them to the lower 48 + DC, simplifies them **as a coverage** so shared borders stay shared, and derives each zone's standard offset, DST offset and DST start/end from the IANA tz database. Also extracts the international and state/province boundary lines. `--year` (default: this year). |
| `rdst basemap` | `data/raw/` | `data/processed/basemap/{z}/{x}/{y}.jpg` | Renders the terrain + bathymetry tile pyramid (see below). `--max-zoom` overrides the automatic choice. |
| `rdst solar` | `data/processed/` | `data/processed/solar/*.json` | For every point and every day of the year computes sunrise/sunset, applies each scenario's UTC offset for that day, keeps the annual extreme, then contours it into colour bands and labelled isochrones clipped exactly to each zone. 12 datasets = {sunrise, sunset} × {latest, earliest} × 3 scenarios. |
| `rdst build` | `data/processed/` | `site/` | Assembles the static site: Leaflet (vendored), data, basemap tiles, lazily-loaded sunrise/sunset datasets. `--no-solar` skips the latter. |
| `rdst all` | | | Runs all five. |

Run `rdst <stage> --help` for options. Everything downloaded is parsed as data only; nothing is executed.

## How the numbers are made

* **DST rules** come from Python's `zoneinfo` (IANA tzdata), sampled at local noon for each day of the
  year, not hard-coded. For 2026 that gives 8 March – 31 October as the last full DST day, matching U.S. law.
* **Sun times** use the NOAA solar-position approximation (equation of time + declination, 90.833° zenith).
  They agree with published almanac times to about a minute (see `tests/test_rules_and_solar.py`).
* **"Latest / earliest of the year"** is evaluated per pixel over all 365 days, so it can fall on different
  dates in different places. Under current law the *latest sunrise* is often the morning of the March clock
  change rather than a January day, which is why rescinding DST moves it by minutes and permanent DST by
  less than a full hour in some cities. The *earliest sunset* is identical under current law and rescinded DST.
* **Zone shapes** are the tz database's zones (county-level in places: Indiana, Kentucky, North Dakota, the
  Navajo Nation in `America/Denver`, Michigan's Menominee zone…), not state boundaries.
* **Colour**: UTC offsets use a validated single-hue ordinal ramp. Sunrise bands use the
  [ColorBrewer](https://colorbrewer2.org/) **YlOrRd** sequential scheme (dawn: pale yellow to deep red) and sunset
  bands use **RdPu** (twilight: pale pink to deep purple), each in ColorBrewer's own 7- or 8-class version, light = earlier,
  dark = later. Each view has one scale shared by both sides of the swipe. A slider fades the data layer so the
  terrain shows through.

## Basemap

`rdst basemap` draws Web-Mercator 256 px JPEG tiles (`{z}/{x}/{y}.jpg`) straight from data:

* **Land**: colour ramp in **feet above sea level** (`LAND_RAMP_FT`: sea-level green through tan and brown to grey at 14,000 ft+).
* **Ocean and lakes**: colour ramp in **feet of depth** (`BATHY_RAMP_FT`: pale blue at the surface to navy at 20,000 ft). Ocean depth is
  measured below sea level. Each lake is measured below its *own* surface (`LAKE_SURFACE_FT` lists the big ones, e.g.
  Superior 600 ft; others use the 95th percentile of the DEM inside the lake), so Lake Superior reads about 0 to 1,300 ft deep rather than as 600 ft above to 700 ft below sea level.
* **Hillshade** (light from the NW, vertically exaggerated) on both land and water; coastlines are anti-aliased from
  the Natural Earth 10 m ocean and lake polygons.
* Both ramps are legends in the sidebar; edit the stops in `config.py` to restyle.

The elevation grid is chosen with `rdst fetch --dem`:

| Option | Source | Notes |
|---|---|---|
| `etopo2022` (default) | NOAA NCEI [ETOPO 2022](https://www.ncei.noaa.gov/products/etopo-global-relief-model) surface model, read over OPeNDAP so only the North America window is transferred | `--dem-resolution 60s` (≈1.8 km, ≈45 MB, default) or `30s` (≈0.9 km, ≈170 MB). Includes ocean bathymetry and surveyed bathymetry for the very large lakes (the Great Lakes among them). Tiles go to zoom 7. Not for navigation (NOAA's terms). |
| `etopo10` | ETOPO1 at 10 arc-minutes (≈18 km), a ≈1 MB file hosted on GitHub | Coarse: tiles stop at zoom 5 and look soft. Meant as a fallback when NOAA is unreachable. Lake detail is poor. |
| `--dem-file path.nc` | your own NetCDF grid in metres | Variable `z`/`elevation`/`topography`, coordinates `lon`/`lat` (any order); bathymetry must be negative. |

The ETOPO 2022 download path was written against NOAA's published OPeNDAP layout but could not be run from the
environment this repo was developed in (no access to `ngdc.noaa.gov`); the rendering chain itself was exercised end to end on the
10 arc-minute grid and in the tests. If NOAA's server changes or is unreachable, `rdst fetch` says so and you can use
`--dem etopo10` or `--dem-file`.

Boundary styling (in `app.js`, drawn bottom to top): time-zone borders (thick white with a dark edge), state and
province lines (white casing + near-black line), then international borders (wide white casing + heavy black line).
Sunrise/sunset isochrones are dashed so they cannot be mistaken for borders.

## Configuration

Everything tunable is in [`src/rdst/config.py`](src/rdst/config.py): colour ramps, band width
(`SOLAR_BIN_MINUTES`), per-view scales (`SOLAR_SCALES`), the city list (`CITIES`), simplification
tolerance, contour resolution. Add a scenario by extending `ZoneRule.offset_on` in `zones.py` and
`SCENARIOS` in `config.py`.

## Deploy to GitHub Pages

`.github/workflows/pages.yml` runs the tests, builds the site and publishes it on every push to `main`
(and monthly, to pick up new tzdata / boundary releases). In the repository settings choose
**Pages → Source: GitHub Actions**. Generated output (`data/`, `site/`) is git-ignored.

## Layout

```
src/rdst/
  config.py     constants, colour ramps (ColorBrewer, feet-based terrain/bathymetry), scales, cities
  fetch.py      download + provenance manifest
  dem.py        elevation/bathymetry grid (ETOPO 2022 OPeNDAP, ETOPO1 fallback, local file)
  zones.py      CONUS zones, DST rules, internal zone borders, zone labels
  boundaries.py international + state lines, state labels
  basemap.py    terrain + bathymetry tile pyramid (hillshade, lake depths, anti-aliased coasts)
  solar.py      sun maths, annual extremes, contours, isochrones
  build.py      static site assembly
  pipeline.py   stage orchestration
  cli.py        `rdst` command
  web/          index.html, app.js (swipe + layers), style.css, vendor/leaflet
tests/          rules, sun-time accuracy, basemap maths, synthetic end-to-end pipeline
```

## Data & licences

* Zone boundaries: [Timezone Boundary Builder](https://github.com/evansiroky/timezone-boundary-builder),
  © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/). Maps that use it must keep
  that attribution (the site's footer does).
* Shorelines, lakes, state and international boundary lines: [Natural Earth](https://www.naturalearthdata.com/) (public domain).
* Elevation and bathymetry: NOAA NCEI [ETOPO 2022](https://doi.org/10.25921/fd45-gt74) (public domain); cite
  NOAA National Centers for Environmental Information. 2022. *ETOPO 2022 15 Arc-Second Global Relief Model.*
* Sunrise/sunset colour schemes: [ColorBrewer](https://colorbrewer2.org/) YlOrRd and RdPu, © Cynthia A. Brewer,
  Pennsylvania State University (Apache-2.0); hex values taken from the `palettable` package.
* DST rules: [IANA tz database](https://www.iana.org/time-zones) (public domain).
* Map library: [Leaflet](https://leafletjs.com/) 1.9.4 (BSD-2-Clause), vendored in `src/rdst/web/vendor/leaflet`.
* The default basemap is self-rendered, so nothing is requested from third parties. The optional OpenStreetMap and
  Esri basemaps in the layer switcher load from those providers under their own terms (the OSM tile servers are not
  meant for heavy traffic). CARTO's free tiles were removed because they now require an API key.

No licence file is included yet: add the one you want before publishing.
