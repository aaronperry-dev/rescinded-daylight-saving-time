"""Constants shared by every pipeline stage."""
from __future__ import annotations

from datetime import date

# --- Sources -----------------------------------------------------------------
# "latest/download" redirects to the newest tagged release without needing the
# (rate-limited) GitHub API. Pin a tag with `rdst fetch --tz-release 2026f`.
TZ_LATEST_URL = (
    "https://github.com/evansiroky/timezone-boundary-builder/"
    "releases/latest/download/timezones.geojson.zip"
)
TZ_TAG_URL = (
    "https://github.com/evansiroky/timezone-boundary-builder/"
    "releases/download/{tag}/timezones.geojson.zip"
)
NE_BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
TZ_ZIP_NAME = "timezones.geojson.zip"
NE_STATES_NAME = "ne_10m_admin_1_states_provinces.geojson"   # polygons: CONUS mask + state labels
NE_STATE_LINES_NAME = "ne_10m_admin_1_states_provinces_lines.geojson"
NE_COUNTRY_LINES_NAME = "ne_10m_admin_0_boundary_lines_land.geojson"
NE_OCEAN_NAME = "ne_10m_ocean.geojson"
NE_LAKES_NAMES = ("ne_10m_lakes.geojson", "ne_10m_lakes_north_america.geojson")
NE_FILES = (NE_STATES_NAME, NE_STATE_LINES_NAME, NE_COUNTRY_LINES_NAME, NE_OCEAN_NAME, *NE_LAKES_NAMES)

# --- Geography ---------------------------------------------------------------
EXCLUDED_STATES = {"AK", "HI"}          # everything else in the USA layer is CONUS (+DC)
# Every IANA zone that covers U.S. land starts with this prefix. It lets the
# streaming reader skip Asia/Europe/Africa geometry without building it.
TZID_PREFIX = "America/"
COUNTRY_CODE = "US"                     # zone.tab country used to pick real U.S. zones
FOREIGN_AREA_WARN = 0.5                 # deg^2; warn if a non-U.S. zone covers this much of CONUS

# --- Geometry processing -----------------------------------------------------
SIMPLIFY_TOLERANCE = 0.004   # degrees (~400 m); coverage-simplified so borders stay shared
MIN_ZONE_AREA = 0.01         # deg^2; drops Canadian/Mexican slivers left by the mask clip
MIN_PART_AREA = 0.002        # deg^2; drops specks inside multipolygons
COORD_DECIMALS = 3

# --- Scenarios ---------------------------------------------------------------
CURRENT = "current"
RESCINDED = "rescinded"
PERMANENT = "permanent_dst"
SCENARIOS = {
    CURRENT: "Current law – DST observed",
    RESCINDED: "DST rescinded – standard time all year",
    PERMANENT: "Permanent DST – clocks stay forward all year",
}
SCENARIO_SHORT = {CURRENT: "Current", RESCINDED: "Rescinded", PERMANENT: "Permanent DST"}

# --- Colour ------------------------------------------------------------------
# Ordinal blue ramp (UTC-4 .. UTC-8, light -> dark). Validated with the dataviz
# skill's validate_palette.js --ordinal --mode light (monotone L, single hue).
OFFSET_RAMP = {
    "-4": "#86b6ef",
    "-5": "#5598e7",
    "-6": "#2a78d6",
    "-7": "#1c5cab",
    "-8": "#104281",
}
FALLBACK_COLOR = "#9a9a96"
# Sunrise / sunset bands use ColorBrewer sequential schemes (light -> dark = earlier -> later).
# Exact class values (7 and 8 classes) from ColorBrewer.org via the `palettable` package.
# Colours (c) Cynthia A. Brewer, Pennsylvania State University (Apache-2.0 licence).
SOLAR_SCHEMES = {"sunrise": "YlOrRd", "sunset": "RdPu"}   # dawn yellow->red; twilight pink->purple
COLORBREWER = {
    "YlOrRd": {
        7: ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#b10026"],
        8: ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#b10026"],
    },
    "RdPu": {
        7: ["#feebe2", "#fcc5c0", "#fa9fb5", "#f768a1", "#dd3497", "#ae017e", "#7a0177"],
        8: ["#fff7f3", "#fde0dd", "#fcc5c0", "#fa9fb5", "#f768a1", "#dd3497", "#ae017e", "#7a0177"],
    },
}

# --- Solar layers ------------------------------------------------------------
FIELD_RESOLUTION = 0.1       # degrees; the clock-time field is smooth, contours interpolate between nodes
SOLAR_BIN_MINUTES = 30       # width of each colour band (and spacing of labelled isochrones)
# (first band start, last band end) in minutes after local midnight, one scale per map
# view so each uses the whole colour ramp. The left and right sides of a swipe always show
# the same view, hence the same scale. The first/last bands are open-ended ("or earlier" /
# "or later"), so a different year can never fall off the scale.
SOLAR_SCALES = {
    ("sunrise", "latest"): (6 * 60 + 30, 10 * 60),
    ("sunrise", "earliest"): (3 * 60 + 30, 7 * 60),
    ("sunset", "latest"): (18 * 60 + 30, 22 * 60 + 30),
    ("sunset", "earliest"): (15 * 60 + 30, 19 * 60),
}
SOLAR_STATS = {          # which day of the year each map shows, per pixel
    "latest": "Latest of the year",
    "earliest": "Earliest of the year",
}
SOLAR_TITLES = {
    ("sunrise", "latest"): "Latest sunrise of the year",
    ("sunrise", "earliest"): "Earliest sunrise of the year",
    ("sunset", "latest"): "Latest sunset of the year",
    ("sunset", "earliest"): "Earliest sunset of the year",
}
SOLAR_METRIC_TITLES = {"sunrise": "Sunrise", "sunset": "Sunset"}
LABEL_MIN_LENGTH = 1.8       # deg; an isochrone piece must be this long to get a label
LINE_SIMPLIFY = 0.004

# Reference cities for the comparison table: (name, tzid, lat, lon).
CITIES = [
    ("Seattle", "America/Los_Angeles", 47.61, -122.33),
    ("Los Angeles", "America/Los_Angeles", 34.05, -118.24),
    ("Phoenix", "America/Phoenix", 33.45, -112.07),
    ("Denver", "America/Denver", 39.74, -104.99),
    ("Minneapolis", "America/Chicago", 44.98, -93.27),
    ("Dallas", "America/Chicago", 32.78, -96.80),
    ("Chicago", "America/Chicago", 41.88, -87.63),
    ("Atlanta", "America/New_York", 33.75, -84.39),
    ("New York", "America/New_York", 40.71, -74.01),
    ("Miami", "America/New_York", 25.76, -80.19),
]


def default_dates(year: int) -> list[date]:
    """The 1st and 15th of every month - 24 stops for the date slider (time-zone view)."""
    return [date(year, m, d) for m in range(1, 13) for d in (1, 15)]


# --- Basemap (terrain relief + bathymetry) -----------------------------------
# A self-rendered XYZ tile pyramid: no tile server, no API key.
BASEMAP_BOUNDS = (-132.0, 17.0, -58.0, 56.0)   # west, south, east, north of the tile coverage
BASEMAP_MIN_ZOOM = 3
BASEMAP_MAX_ZOOM = 7            # ~1 km/px at 40 N; Leaflet upsamples beyond this
TILE_SIZE = 256
DEM_MARGIN = 0.5                # degrees of DEM beyond the tile coverage (hillshade / sampling edges)
FT_PER_M = 3.280839895
JPEG_QUALITY = 85
MIN_LAKE_AREA = 0.004           # deg^2 (~40 km2); smaller lakes are sub-pixel and skipped
# Hillshade: several light directions blended (weights sum to 1) so ridges read naturally instead of
# looking lit by one lamp; strengths are how far the shading moves the colour (0 = none).
HILLSHADE = {"azimuths": [(225.0, 0.15), (270.0, 0.2), (315.0, 0.45), (360.0, 0.2)], "altitude": 45.0,
             "zfactor": 3.0, "land_strength": 0.55, "water_strength": 0.22}
COAST_RGB = (92, 118, 136)      # thin shoreline stroke drawn where land meets water
COAST_ALPHA = 0.42

# Digital elevation model sources (metres, positive up). Both include ocean bathymetry
# and Great Lakes bathymetry; ETOPO 2022 is far sharper.
ETOPO2022_OPENDAP = (
    "https://www.ngdc.noaa.gov/thredds/dodsC/global/ETOPO2022/{res}/"
    "{res}_surface_elev_netcdf/ETOPO_2022_v1_{res}_N90W180_surface.nc"
)
ETOPO2022_RESOLUTIONS = ("60s", "30s")   # one global file each; 15 s is split into 15-degree tiles (not supported)
ETOPO10_URL = ("https://github.com/fatiando-data/earth-topography-10arcmin/"
               "releases/download/v1/earth-topography-10arcmin.nc")
DEM_SOURCES = ("etopo2022", "etopo10")
DEM_FILE_NAME = "dem.npz"

# Land elevation ramp in FEET above sea level: (feet, colour). Piecewise-linear between stops.
LAND_RAMP_FT = [
    (-500, "#a9bfae"), (0, "#cbdbbd"), (500, "#d4e0bf"), (1000, "#dde3c3"), (2000, "#e7e4c6"),
    (3000, "#e8dbb9"), (4000, "#ddc9a6"), (5000, "#d0b793"), (6000, "#c2a384"), (8000, "#af9079"),
    (10000, "#a08c82"), (12000, "#c1b6ae"), (14000, "#ece8e3"),
]
# Water depth ramp in FEET below the water surface (oceans: below sea level; lakes: below the lake).
BATHY_RAMP_FT = [
    (0, "#e4eef3"), (25, "#dae8f0"), (50, "#cfe1ec"), (100, "#c1d8e8"), (200, "#aecce1"),
    (400, "#9abcd6"), (800, "#85a9c9"), (1500, "#7096bb"), (3000, "#5b81a8"), (6000, "#486b94"),
    (10000, "#385781"), (15000, "#2c4770"), (20000, "#223a5e"),
]
# Surface elevations (feet above sea level) of the lakes where bathymetry depth matters most.
# Natural Earth `name` -> feet. Other lakes fall back to the 95th percentile of the DEM inside them.
LAKE_SURFACE_FT = {
    "Lake Superior": 600, "Lake Michigan": 577, "Lake Huron": 577, "Lake St. Clair": 574,
    "Lake Erie": 569, "Lake Ontario": 243, "Lake Champlain": 95, "Great Salt Lake": 4198,
    "Lake Okeechobee": 13, "Salton Sea": -236, "Lake Pontchartrain": 0, "Lake Tahoe": 6225,
    "Lake of the Woods": 1060, "Lake Winnebago": 747, "Lake Powell": 3700, "Lake Mead": 1100,
    "Flathead Lake": 2893, "Utah Lake": 4489, "Pyramid Lake": 3796, "Lake Oahe": 1607,
    "Lake Sakakawea": 1850, "Lake Texoma": 617, "Lake Barkley": 359,
}

# --- Boundaries --------------------------------------------------------------
BOUNDARY_SIMPLIFY = 0.004       # degrees
BOUNDARY_COUNTRIES = ("USA", "CAN", "MEX")
