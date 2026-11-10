"""Stage 3 - sunrise / sunset maps in the style of the "latest sunrise" DST maps.

For every pixel and every day of the year we compute the UTC time of sunrise and
sunset (NOAA solar-position approximation, good to ~1 minute), add the UTC offset
that scenario gives that zone on that day, and keep the annual extreme: the latest
or earliest clock time that place ever sees. The result per dataset is

* filled 30-minute colour bands, clipped exactly to each time-zone polygon,
* isochrones (lines of equal clock time) with a label every half hour, and
* a small table of reference cities,

all as vector GeoJSON, so edges stay sharp at any zoom. Isochrones jump by an hour
at a zone border, which is exactly the sawtooth the DST debate is about.

Datasets are written per (metric, stat, scenario), e.g. ``sunset_latest_rescinded``.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import shapely
from contourpy import FillType, contour_generator
from shapely.geometry import LineString, MultiLineString, Polygon, mapping
from shapely.geometry.base import BaseGeometry

from . import config
from .zones import ZoneRule, round_coords

_ZENITH_COS = math.cos(math.radians(90.833))  # official sunrise/sunset: refraction + solar disc
METRICS = ("sunrise", "sunset")
STATS = tuple(config.SOLAR_STATS)
SCENARIO_KEYS = (config.CURRENT, config.RESCINDED, config.PERMANENT)


# ------------------------------------------------------------------------- physics
def _sun_params(day: date) -> tuple[float, float]:
    """(equation of time in minutes, solar declination in radians) for ``day``."""
    g = 2 * math.pi / 365.0 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g)
    )
    decl = (
        0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g)
    )
    return eqtime, decl


def _events(cos_lat, tan_lat, lon, eqtime, decl):
    cos_ha = _ZENITH_COS / (cos_lat * math.cos(decl)) - tan_lat * math.tan(decl)
    ha = np.degrees(np.arccos(np.clip(cos_ha, -1.0, 1.0)))
    return 720.0 - 4.0 * (lon + ha) - eqtime, 720.0 - 4.0 * (lon - ha) - eqtime


def sun_events_utc_minutes(lat, lon, day: date):
    """Sunrise and sunset as minutes after 00:00 UTC (may fall outside 0-1440).

    ``lat``/``lon`` are degrees (arrays or scalars; east positive). Polar day/night is
    clipped, which never occurs in CONUS.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    latr = np.radians(lat)
    eqtime, decl = _sun_params(day)
    return _events(np.cos(latr), np.tan(latr), lon, eqtime, decl)


def annual_extremes(rule: ZoneRule, lat, lon, year: int) -> dict[tuple[str, str, str], np.ndarray]:
    """Latest/earliest sunrise & sunset clock minutes over ``year``, for all scenarios.

    Returns {(metric, stat, scenario): array shaped like ``lat``}. Only the UTC
    extremes over three day-sets (all / standard-time / DST days) are tracked; the
    scenarios then differ by a constant offset per day-set, so one pass serves all.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    latr = np.radians(lat)
    cos_lat, tan_lat = np.cos(latr), np.tan(latr)
    ops = {"latest": np.maximum, "earliest": np.minimum}
    acc: dict[tuple[str, str, str], np.ndarray] = {}
    day = date(year, 1, 1)
    while day.year == year:
        eqtime, decl = _sun_params(day)
        rise, sett = _events(cos_lat, tan_lat, lon, eqtime, decl)
        groups = ("all", "dst" if rule.dst_active(day) else "std")
        for metric, utc in (("sunrise", rise), ("sunset", sett)):
            for stat, op in ops.items():
                for grp in groups:
                    key = (metric, stat, grp)
                    acc[key] = utc.copy() if key not in acc else op(acc[key], utc)
        day += timedelta(days=1)

    std, dst = 60.0 * rule.std_offset, 60.0 * rule.dst_offset
    out = {}
    for metric in METRICS:
        for stat, op in ops.items():
            allv = acc[(metric, stat, "all")]
            out[(metric, stat, config.RESCINDED)] = allv + std
            out[(metric, stat, config.PERMANENT)] = allv + dst
            if rule.observes_dst:
                out[(metric, stat, config.CURRENT)] = op(acc[(metric, stat, "std")] + std,
                                                          acc[(metric, stat, "dst")] + dst)
            else:
                out[(metric, stat, config.CURRENT)] = allv + std
    return out


# ---------------------------------------------------------------------- formatting
def fmt_clock(minutes: float) -> str:
    h, m = divmod(int(round(minutes)) % 1440, 60)
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def fmt_label(minutes: float) -> str:
    h, m = divmod(int(round(minutes)) % 1440, 60)
    return f"{(h % 12) or 12}:{m:02d}"


def sequential_colors(n: int) -> list[str]:
    """n colours sampled evenly along the validated sequential blue ramp (light -> dark)."""
    stops = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in config.SEQUENTIAL_RAMP]
    out = []
    for i in range(n):
        t = i * (len(stops) - 1) / max(n - 1, 1)
        j = min(int(t), len(stops) - 2)
        f = t - j
        rgb = [round(a + (b - a) * f) for a, b in zip(stops[j], stops[j + 1])]
        out.append("#{:02x}{:02x}{:02x}".format(*rgb))
    return out


def scale_for(metric: str, stat: str) -> tuple[int, int, int]:
    lo, hi = config.SOLAR_SCALES[(metric, stat)]
    return lo, hi, (hi - lo) // config.SOLAR_BIN_MINUTES


def legend_for(metric: str, stat: str) -> dict:
    lo, hi, n = scale_for(metric, stat)
    colors = sequential_colors(n)
    step = config.SOLAR_BIN_MINUTES
    return {
        "bins": [{"color": colors[i], "from": fmt_clock(lo + i * step)} for i in range(n)],
        "end": fmt_clock(hi),
    }


# --------------------------------------------------------------------- contouring
def zone_grid(geom: BaseGeometry, res: float):
    """A lat/lon node grid covering the zone's bounding box (plus one cell of margin)."""
    minx, miny, maxx, maxy = geom.bounds
    xs = np.arange(math.floor(minx / res) * res - res, maxx + 2 * res, res)
    ys = np.arange(math.floor(miny / res) * res - res, maxy + 2 * res, res)
    lon2d, lat2d = np.meshgrid(xs, ys)
    return xs, ys, lon2d, lat2d


def _polys_from_fill(points_list, offsets_list) -> list[Polygon]:
    polys = []
    for pts, offs in zip(points_list, offsets_list):
        rings = [pts[offs[j]:offs[j + 1]] for j in range(len(offs) - 1)]
        if rings and len(rings[0]) >= 4:
            polys.append(Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4]))
    return polys


def _line_parts(g: BaseGeometry):
    if g.is_empty:
        return
    if g.geom_type == "LineString":
        yield g
    elif hasattr(g, "geoms"):
        for part in g.geoms:
            yield from _line_parts(part)


def band_geometries(xs, ys, z, lo, nbins, step, zone_geom) -> dict[int, BaseGeometry]:
    """{band index: polygon} for the part of ``zone_geom`` falling in each clock-time band."""
    gen = contour_generator(xs, ys, z, fill_type=FillType.OuterOffset)
    zmin, zmax = float(z.min()), float(z.max())
    big = 1e9
    out = {}
    for k in range(nbins):
        b_lo = -big if k == 0 else lo + k * step
        b_hi = big if k == nbins - 1 else lo + (k + 1) * step
        if b_hi <= zmin or b_lo > zmax:
            continue
        polys = _polys_from_fill(*gen.filled(b_lo, b_hi))
        if not polys:
            continue
        g = shapely.union_all(polys).intersection(zone_geom)
        if not g.is_empty:
            out[k] = g
    return out


def _label_for(piece: LineString, text: str):
    mid = piece.interpolate(0.5, normalized=True)
    a, b = piece.interpolate(0.45, normalized=True), piece.interpolate(0.55, normalized=True)
    ang = math.degrees(math.atan2(b.y - a.y, (b.x - a.x) * math.cos(math.radians(mid.y))))
    if ang > 90:
        ang -= 180
    elif ang <= -90:
        ang += 180
    return [round(mid.y, 3), round(mid.x, 3), text, round(-ang, 1)]  # CSS rotates clockwise


def isochrones(xs, ys, z, lo, hi, step, zone_geom):
    """Lines of equal clock time clipped to the zone, plus one label per line."""
    gen = contour_generator(xs, ys, z)
    zmin, zmax = float(z.min()), float(z.max())
    lines: dict[int, list[LineString]] = defaultdict(list)
    labels = []
    for level in range(lo, hi + 1, step):
        if level < zmin or level > zmax:
            continue
        pieces = []
        for arr in gen.lines(level):
            if len(arr) >= 2:
                pieces += [p for p in _line_parts(LineString(arr).intersection(zone_geom)) if p.length > 0]
        if not pieces:
            continue
        lines[level] += pieces
        best = max(pieces, key=lambda p: p.length)
        if best.length >= config.LABEL_MIN_LENGTH:
            labels.append(_label_for(best, fmt_label(level)))
    return lines, labels


# ----------------------------------------------------------------------- the stage
def _feature(geom: BaseGeometry, props: dict) -> dict:
    m = mapping(geom)
    return {"type": "Feature", "properties": props,
            "geometry": {"type": m["type"], "coordinates": round_coords(m["coordinates"], config.COORD_DECIMALS)}}


def build_solar(
    zones: list[tuple[ZoneRule, BaseGeometry]],
    year: int,
    out_dir: Path,
    res: float = config.FIELD_RESOLUTION,
) -> dict:
    """Compute every dataset, write ``<key>.json`` files and return the site manifest."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    step = config.SOLAR_BIN_MINUTES

    keys = [(m, s, sc) for m in METRICS for s in STATS for sc in SCENARIO_KEYS]
    bands = {k: defaultdict(list) for k in keys}
    lines = {k: defaultdict(list) for k in keys}
    labels = {k: [] for k in keys}
    clamped: dict[tuple, float] = {}

    print(f"solar: contouring {len(zones)} zones x {len(keys)} datasets at {res}° for {year}")
    for rule, geom in zones:
        xs, ys, lon2d, lat2d = zone_grid(geom, res)
        inside = shapely.contains_xy(geom, lon2d, lat2d)
        fields = annual_extremes(rule, lat2d, lon2d, year)
        for key, z in fields.items():
            lo, hi, nbins = scale_for(key[0], key[1])
            if inside.any():
                zin = z[inside]
                if zin.min() < lo or zin.max() >= hi:
                    clamped[key] = max(clamped.get(key, 0), float(max(lo - zin.min(), zin.max() - hi + 1)))
            for k, g in band_geometries(xs, ys, z, lo, nbins, step, geom).items():
                bands[key][k].append(g)
            ln, lb = isochrones(xs, ys, z, lo, hi, step, geom)
            for level, pieces in ln.items():
                lines[key][level] += pieces
            labels[key] += lb
    for key, over in clamped.items():
        print(f"solar: WARNING {key} has values up to {over:.0f} min outside the colour scale (clamped)")

    # reference cities, computed with exactly the same maths as the maps
    rules = {r.tzid: r for r, _ in zones}
    city_list = [c for c in config.CITIES if c[1] in rules]
    cities = {k: {} for k in keys}
    for name, tzid, lat, lon in city_list:
        pt = annual_extremes(rules[tzid], np.array([lat]), np.array([lon]), year)
        for key, v in pt.items():
            cities[key][name] = round(float(v[0]), 1)

    datasets = []
    for key in keys:
        metric, stat, scen = key
        feats = [_feature(shapely.union_all(gs), {"bin": k}) for k, gs in sorted(bands[key].items())]
        line_feats = [
            _feature(MultiLineString(pieces).simplify(config.LINE_SIMPLIFY), {"t": level})
            for level, pieces in sorted(lines[key].items())
        ]
        name = f"{metric}_{stat}_{scen}"
        payload = {
            "key": name, "metric": metric, "stat": stat, "scenario": scen,
            "bands": {"type": "FeatureCollection", "features": feats},
            "lines": {"type": "FeatureCollection", "features": line_feats},
            "labels": labels[key],
            "cities": cities[key],
        }
        (out_dir / f"{name}.json").write_text(json.dumps(payload, separators=(",", ":")))
        datasets.append(name)
    size = sum(p.stat().st_size for p in out_dir.glob("*.json")) / 1e6
    print(f"solar: wrote {len(datasets)} datasets ({size:.1f} MB)")

    return {
        "year": year,
        "binMinutes": step,
        "metrics": {m: config.SOLAR_METRIC_TITLES[m] for m in METRICS},
        "stats": config.SOLAR_STATS,
        "views": {f"{m}_{s}": {"title": config.SOLAR_TITLES[(m, s)], "legend": legend_for(m, s)}
                  for m in METRICS for s in STATS},
        "cities": [c[0] for c in city_list],
        "datasets": datasets,
    }
