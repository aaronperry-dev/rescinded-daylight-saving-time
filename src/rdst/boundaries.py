"""Administrative boundary lines (international + state/province) and state labels.

Drawn as lines, not polygons, so the web map can style the two classes differently
(heavier line for international borders) and so shared borders are drawn once.
"""
from __future__ import annotations

import json
from pathlib import Path

import shapely
from shapely.geometry import box, mapping, shape
from shapely.ops import linemerge

from . import config
from .zones import _round_coords

_COUNTRY_NAMES = {"USA": "United States of America", "CAN": "Canada", "MEX": "Mexico"}


def _lines(geom):
    """Flatten to a list of simple LineStrings."""
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        return [g for part in geom.geoms for g in _lines(part)]
    return []


def _collect(features, keep, clip, tol):
    geoms = [shape(f["geometry"]) for f in features if keep(f["properties"])]
    if not geoms:
        return []
    merged = shapely.unary_union(shapely.clip_by_rect(shapely.union_all(geoms), *clip.bounds))
    merged = linemerge(_lines(merged)) if _lines(merged) else merged
    out = []
    for ln in _lines(merged):
        ln = ln.simplify(tol, preserve_topology=False)
        if not ln.is_empty and ln.length > 0.01:
            out.append(ln)
    return out


def build_boundaries(raw_dir: Path) -> dict:
    """International and state/province lines inside the basemap extent, as one FeatureCollection."""
    raw_dir = Path(raw_dir)
    clip = box(*config.BASEMAP_BOUNDS)
    tol = config.BOUNDARY_SIMPLIFY

    with open(raw_dir / config.NE_COUNTRY_LINES_NAME, encoding="utf-8") as fh:
        country = json.load(fh)["features"]
    with open(raw_dir / config.NE_STATE_LINES_NAME, encoding="utf-8") as fh:
        states = json.load(fh)["features"]

    wanted = set(_COUNTRY_NAMES.values())
    intl = _collect(country, lambda p: p.get("ADM0_LEFT") in wanted or p.get("ADM0_RIGHT") in wanted, clip, tol)
    state = _collect(states, lambda p: p.get("ADM0_A3") in config.BOUNDARY_COUNTRIES, clip, tol)

    feats = []
    for kind, lines in (("state", state), ("international", intl)):
        for ln in lines:
            m = mapping(ln)
            feats.append({"type": "Feature", "properties": {"kind": kind},
                          "geometry": {"type": "LineString", "coordinates": _round_coords(m["coordinates"], 3)}})
    return {"type": "FeatureCollection", "features": feats}


def build_state_labels(states_path: Path) -> list[dict]:
    """Postal-code label anchors for the lower-48 + DC (polylabel of the largest part)."""
    from shapely.ops import polylabel

    with open(states_path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for f in data["features"]:
        p = f["properties"]
        if p.get("adm0_a3") != "USA" or p.get("postal") in config.EXCLUDED_STATES:
            continue
        g = shape(f["geometry"])
        g = g if g.is_valid else shapely.make_valid(g)
        biggest = max(getattr(g, "geoms", [g]), key=lambda x: x.area)
        pt = polylabel(biggest, tolerance=0.02)
        out.append({"text": p["postal"], "lat": round(pt.y, 3), "lon": round(pt.x, 3)})
    return sorted(out, key=lambda d: d["text"])
