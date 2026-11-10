"""Stage 2 - CONUS time-zone polygons + DST rules.

Geometry comes from timezone-boundary-builder (legal zone boundaries), clipped to
the lower-48 + DC outline from Natural Earth. Rules (standard offset, DST offset,
DST start/end) are derived from the IANA tz database via ``zoneinfo`` rather than
hard-coded, so they track whatever tzdata the machine has.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import ijson
import shapely
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from . import config

_GROUP_NAMES = {-5.0: "Eastern", -6.0: "Central", -7.0: "Mountain", -8.0: "Pacific"}


# --------------------------------------------------------------------------- rules
@dataclass(frozen=True)
class ZoneRule:
    tzid: str
    std_offset: float          # hours from UTC on standard time
    dst_offset: float          # hours from UTC while DST is in effect (== std if none)
    observes_dst: bool
    dst_start: str | None      # ISO date: first calendar day DST is in effect
    dst_end: str | None        # ISO date: last calendar day DST is in effect
    std_abbr: str
    dst_abbr: str
    group: str                 # friendly name, e.g. "Mountain (no DST)"

    def dst_active(self, day: date) -> bool:
        if not self.observes_dst:
            return False
        return date.fromisoformat(self.dst_start) <= day <= date.fromisoformat(self.dst_end)

    def offset_on(self, day: date, scenario: str) -> float:
        """UTC offset (hours) in force on ``day`` under ``scenario``."""
        if scenario == config.RESCINDED:
            return self.std_offset
        if scenario == config.PERMANENT:
            return self.dst_offset  # zones that never observe DST have dst_offset == std_offset
        if scenario == config.CURRENT:
            return self.dst_offset if self.dst_active(day) else self.std_offset
        raise ValueError(f"unknown scenario {scenario!r}")


def group_name(std_offset: float, observes_dst: bool) -> str:
    base = _GROUP_NAMES.get(std_offset, f"UTC{std_offset:+g}")
    return base if observes_dst else f"{base} (no DST)"


def compute_rule(tzid: str, year: int) -> ZoneRule:
    """Derive a zone's DST rule for ``year`` by sampling local noon on every day."""
    tz = ZoneInfo(tzid)
    zero = timedelta(0)
    std_offsets: set[float] = set()
    dst_offsets: set[float] = set()
    dst_days: list[date] = []
    std_abbr = dst_abbr = ""
    day = date(year, 1, 1)
    while day.year == year:
        local = datetime(day.year, day.month, day.day, 12, tzinfo=tz)
        off = local.utcoffset()
        dst = local.dst() or zero
        std_offsets.add((off - dst).total_seconds() / 3600)
        if dst:
            dst_days.append(day)
            dst_offsets.add(off.total_seconds() / 3600)
            dst_abbr = local.tzname() or ""
        else:
            std_abbr = local.tzname() or ""
        day += timedelta(days=1)

    if len(std_offsets) != 1 or len(dst_offsets) > 1:
        raise ValueError(f"{tzid} changes its standard offset during {year}; not supported")
    std = std_offsets.pop()
    if not dst_days:
        return ZoneRule(tzid, std, std, False, None, None, std_abbr, std_abbr, group_name(std, False))
    if (dst_days[-1] - dst_days[0]).days + 1 != len(dst_days):
        raise ValueError(f"{tzid} has more than one DST period in {year}; not supported")
    return ZoneRule(
        tzid, std, dst_offsets.pop(), True,
        dst_days[0].isoformat(), dst_days[-1].isoformat(),
        std_abbr, dst_abbr, group_name(std, True),
    )


# ----------------------------------------------------------------------- geometry
def _valid(g: BaseGeometry) -> BaseGeometry:
    return g if g.is_valid else shapely.make_valid(g)


def load_conus_mask(states_path: Path) -> BaseGeometry:
    """Union of the lower-48 + DC from the Natural Earth admin-1 file."""
    with open(states_path, encoding="utf-8") as fh:
        data = json.load(fh)
    parts = []
    for f in data["features"]:
        p = f["properties"]
        if p.get("adm0_a3") == "USA" and p.get("postal") not in config.EXCLUDED_STATES:
            parts.append(_valid(shape(f["geometry"])))
    if not parts:
        raise ValueError("No U.S. states found in the Natural Earth file")
    return shapely.union_all(parts)


def stream_zones(zip_path: Path, within: BaseGeometry) -> Iterator[tuple[str, BaseGeometry]]:
    """Yield (tzid, geometry) for zones that touch ``within``, one feature at a time.

    The combined GeoJSON is ~170 MB; ``json.load`` peaks at ~1.4 GB, streaming ~70 MB.
    """
    box = shapely.box(*within.bounds)
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.endswith(".json") or n.endswith(".geojson"))
        with z.open(member) as fh:
            for feat in ijson.items(fh, "features.item", use_float=True):
                tzid = feat["properties"]["tzid"]
                if not tzid.startswith(config.TZID_PREFIX):
                    continue
                geom = _valid(shape(feat["geometry"]))
                if geom.intersects(box):
                    yield tzid, geom


def us_tzids() -> set[str]:
    """IANA zone ids that the tz database assigns to the United States (zone.tab).

    Membership is the reliable way to tell a real U.S. zone from a Canadian or
    Mexican zone whose boundary merely overlaps the state outlines by a sliver.
    """
    from importlib import resources

    candidates = []
    try:
        candidates.append(resources.files("tzdata.zoneinfo").joinpath("zone.tab"))
    except ModuleNotFoundError:
        pass
    candidates.append(Path("/usr/share/zoneinfo/zone.tab"))
    for cand in candidates:
        try:
            text = cand.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            continue
        ids = set()
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) >= 3 and cols[0] == config.COUNTRY_CODE:
                ids.add(cols[2])
        if ids:
            return ids
    raise RuntimeError("zone.tab not found; install the `tzdata` package")


def _drop_small_parts(g: BaseGeometry, min_area: float) -> BaseGeometry:
    if g.geom_type != "MultiPolygon":
        return g
    parts = sorted(g.geoms, key=lambda p: p.area, reverse=True)
    kept = [p for i, p in enumerate(parts) if i == 0 or p.area >= min_area]
    return kept[0] if len(kept) == 1 else shapely.MultiPolygon(kept)


def clip_to_conus(
    zones: list[tuple[str, BaseGeometry]],
    mask: BaseGeometry,
    us_ids: set[str] | None = None,
) -> dict[str, BaseGeometry]:
    """Intersect each zone with the CONUS mask, keeping only zones the tz database calls U.S.

    ``us_ids=None`` skips the country filter (used by tests with synthetic zones).
    A non-U.S. zone that still covers a large part of the mask is reported, since it
    would mean zone.tab and the boundary release disagree.
    """
    out: dict[str, BaseGeometry] = {}
    for tzid, g in zones:
        clipped = _valid(g.intersection(mask))
        if us_ids is not None and tzid not in us_ids:
            if clipped.area > config.FOREIGN_AREA_WARN:
                print(f"process: WARNING {tzid} is not a U.S. zone per zone.tab but covers {clipped.area:.2f} deg² of CONUS; skipped")
            continue
        clipped = shapely.get_parts(clipped)  # keep only polygonal pieces
        polys = [p for p in clipped if p.geom_type == "Polygon" and not p.is_empty]
        if not polys:
            continue
        merged = shapely.union_all(polys)
        if merged.area < config.MIN_ZONE_AREA:
            continue
        out[tzid] = _drop_small_parts(merged, config.MIN_PART_AREA)
    return out


def simplify_coverage(geoms: dict[str, BaseGeometry], tolerance: float) -> dict[str, BaseGeometry]:
    """Simplify all zones together so shared borders stay shared (no gaps/overlaps).

    Falls back to per-polygon simplification if the zones don't form a valid coverage.
    """
    ids = list(geoms)
    arr = [geoms[i] for i in ids]
    try:
        if shapely.coverage_is_valid(arr):
            simplified = list(shapely.coverage_simplify(arr, tolerance))
            return {i: _valid(g) for i, g in zip(ids, simplified)}
        print("process: zones are not a clean coverage; using per-zone simplification")
    except (AttributeError, shapely.errors.GEOSException) as err:
        print(f"process: coverage simplification unavailable ({err}); using per-zone simplification")
    return {i: _valid(g.simplify(tolerance, preserve_topology=True)) for i, g in geoms.items()}


def _round_coords(obj, nd: int):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(c, nd) for c in obj]
        return [_round_coords(o, nd) for o in obj]
    return obj


round_coords = _round_coords


def to_geojson(zones: list[tuple[ZoneRule, BaseGeometry]], nd: int = config.COORD_DECIMALS) -> dict:
    feats = []
    for rule, geom in zones:
        m = mapping(geom)
        feats.append({
            "type": "Feature",
            "properties": asdict(rule),
            "geometry": {"type": m["type"], "coordinates": _round_coords(m["coordinates"], nd)},
        })
    return {"type": "FeatureCollection", "features": feats}


def read_processed(path: Path) -> list[tuple[ZoneRule, BaseGeometry]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [(ZoneRule(**f["properties"]), shape(f["geometry"])) for f in data["features"]]


# ------------------------------------------------------------------ orchestration
def build_conus_zones(zip_path: Path, states_path: Path, year: int) -> list[tuple[ZoneRule, BaseGeometry]]:
    mask = load_conus_mask(states_path)
    raw = list(stream_zones(zip_path, mask))
    print(f"process: {len(raw)} candidate zones touch the CONUS bounding box")
    clipped = clip_to_conus(raw, mask, us_tzids())
    simplified = simplify_coverage(clipped, config.SIMPLIFY_TOLERANCE)
    rounded = {k: shapely.set_precision(v, 10 ** -config.COORD_DECIMALS) for k, v in simplified.items()}
    result = []
    for tzid in sorted(rounded, key=lambda t: (-rounded[t].area, t)):
        result.append((compute_rule(tzid, year), rounded[tzid]))
    return result


# ----------------------------------------------------------------- map furniture
def build_states(states_path: Path, tolerance: float = 0.01) -> dict:
    """Lower-48 + DC state outlines for the thin grey borders drawn over the bands."""
    with open(states_path, encoding="utf-8") as fh:
        data = json.load(fh)
    ids, geoms = [], []
    for f in data["features"]:
        p = f["properties"]
        if p.get("adm0_a3") == "USA" and p.get("postal") not in config.EXCLUDED_STATES:
            ids.append(p["postal"])
            geoms.append(_valid(shape(f["geometry"])))
    try:
        simp = list(shapely.coverage_simplify(geoms, tolerance)) if shapely.coverage_is_valid(geoms) else None
    except shapely.errors.GEOSException:
        simp = None
    if simp is None:
        simp = [g.simplify(tolerance, preserve_topology=True) for g in geoms]
    feats = []
    for pid, g in zip(ids, simp):
        m = mapping(g)
        feats.append({"type": "Feature", "properties": {"postal": pid},
                      "geometry": {"type": m["type"], "coordinates": _round_coords(m["coordinates"], 2)}})
    return {"type": "FeatureCollection", "features": feats}


def group_labels(zones: list[tuple[ZoneRule, BaseGeometry]]) -> list[dict]:
    """Label anchors for the zone groups ("Eastern", "Central", ...), like the reference maps.

    Groups without a clean name (e.g. "Mountain (no DST)") are skipped.
    """
    from shapely.ops import polylabel

    by_group: dict[str, list[BaseGeometry]] = {}
    for rule, geom in zones:
        if rule.group in _GROUP_NAMES.values():
            by_group.setdefault(rule.group, []).append(geom)
    out = []
    for name, geoms in by_group.items():
        merged = shapely.union_all(geoms)
        biggest = max(getattr(merged, "geoms", [merged]), key=lambda p: p.area)
        pt = polylabel(biggest, tolerance=0.05)
        out.append({"text": name.upper(), "lat": round(pt.y, 3), "lon": round(pt.x, 3)})
    return out
