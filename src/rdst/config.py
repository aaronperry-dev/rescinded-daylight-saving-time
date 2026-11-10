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
NE_STATES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_1_states_provinces.geojson"
)
TZ_ZIP_NAME = "timezones.geojson.zip"
NE_STATES_NAME = "ne_50m_admin_1_states_provinces.geojson"

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
# 13-step sequential blue ramp (steps 100 -> 700) for the sunrise/sunset rasters.
SEQUENTIAL_RAMP = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
    "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]

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
