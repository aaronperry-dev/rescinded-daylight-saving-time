"""Stage - render the terrain-relief + bathymetry basemap as an XYZ tile pyramid.

Land is coloured by elevation in **feet above sea level**; the ocean and lakes by **depth in feet**
below their water surface. Both are shaded with a hillshade. Everything is drawn from a DEM and
Natural Earth polygons, so there is no tile server and no API key. Tiles are Web-Mercator
(EPSG:3857) 256 px JPEGs at ``{z}/{x}/{y}.jpg``, which is what Leaflet's ``L.tileLayer`` expects.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageDraw
from shapely.geometry import box, shape
from shapely.strtree import STRtree

from . import config, dem

SUPERSAMPLE = 2            # render at 2x and box-filter down: anti-aliased coastlines, smooth shading
NODATA_RGB = (226, 232, 236)
_SURFACE_PCT = 95          # lake surface = this percentile of the DEM inside the lake (when not listed)


# --------------------------------------------------------------------------- colour ramps
def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def apply_ramp(values: np.ndarray, stops: list[tuple[float, str]]) -> np.ndarray:
    """Piecewise-linear colour lookup. ``values`` (any shape) -> uint8-range float RGB (..., 3)."""
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    cols = np.array([_hex_rgb(s[1]) for s in stops], dtype=np.float64)
    return np.stack([np.interp(values, xs, cols[:, i]) for i in range(3)], axis=-1)


def ramp_info(stops: list[tuple[float, str]]) -> list[dict]:
    return [{"ft": s[0], "color": s[1]} for s in stops]


# --------------------------------------------------------------------------- terrain
def hillshade_grid(lon: np.ndarray, lat: np.ndarray, z_m: np.ndarray, *, azimuth: float, altitude: float,
                   zfactor: float) -> np.ndarray:
    """Hillshade on the DEM grid itself (so the tile renderer only has to resample it).

    Returns the cosine of the angle between the surface normal and the light, 0..1; a flat surface
    gives sin(altitude). ``lat`` must be ascending.
    """
    dlat = float(np.mean(np.diff(lat)))
    dlon = float(np.mean(np.diff(lon)))
    m_per_deg = 111_320.0
    dy = dlat * 110_574.0
    dx = dlon * m_per_deg * np.cos(np.radians(lat))[:, None]
    zf64 = z_m.astype(np.float64)
    dz_dy = np.gradient(zf64, dy, axis=0)           # metres per metre, north positive
    dz_dx = np.gradient(zf64, axis=1) / dx          # per-row spacing: divide after differencing
    # coarse grids smooth relief away, so exaggerate more as cells get bigger
    cell_m = dlat * 110_574.0
    zf = zfactor * max(1.0, cell_m / 1850.0) ** 0.5
    nx, ny, nz = -zf * dz_dx, -zf * dz_dy, np.ones_like(dz_dx)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    az, alt = math.radians(azimuth), math.radians(altitude)
    lx, ly, lz = math.sin(az) * math.cos(alt), math.cos(az) * math.cos(alt), math.sin(alt)
    return np.clip((nx * lx + ny * ly + nz * lz) / norm, 0.0, 1.0)


def _frac_index(axis: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Index of the cell below each query coordinate and the fraction towards the next one."""
    i = np.clip(np.searchsorted(axis, q) - 1, 0, axis.size - 2)
    f = np.clip((q - axis[i]) / (axis[i + 1] - axis[i]), 0.0, 1.0)
    return i, f


def sample_bilinear(grid: np.ndarray, lon: np.ndarray, lat: np.ndarray,
                    qlon: np.ndarray, qlat: np.ndarray) -> np.ndarray:
    """Bilinear sample of ``grid[lat, lon]`` on the separable query grid (qlat rows x qlon cols)."""
    ix, fx = _frac_index(lon, qlon)
    iy, fy = _frac_index(lat, qlat)
    g00 = grid[np.ix_(iy, ix)]
    g01 = grid[np.ix_(iy, ix + 1)]
    g10 = grid[np.ix_(iy + 1, ix)]
    g11 = grid[np.ix_(iy + 1, ix + 1)]
    fx, fy = fx[None, :], fy[:, None]
    return (g00 * (1 - fx) + g01 * fx) * (1 - fy) + (g10 * (1 - fx) + g11 * fx) * fy


# --------------------------------------------------------------------------- tile maths
def tile_lonlat(z: int, x: int, y: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Lon (n,) and lat (n,) of the pixel centres of an n x n render of tile z/x/y."""
    t = (np.arange(n) + 0.5) / n
    lon = (x + t) / 2**z * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + t) / 2**z))))
    return lon, lat


def lonlat_to_tile_px(lon: np.ndarray, lat: np.ndarray, z: int, x: int, y: int, n: int):
    """Pixel coordinates inside an n x n render of tile z/x/y."""
    scale = 2**z
    px = ((lon + 180.0) / 360.0 * scale - x) * n
    s = np.sin(np.radians(np.clip(lat, -85.05, 85.05)))
    py = (0.5 - np.log((1 + s) / (1 - s)) / (4 * np.pi)) * scale
    return px, (py - y) * n


def tile_bounds_deg(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    w = x / 2**z * 360.0 - 180.0
    e = (x + 1) / 2**z * 360.0 - 180.0
    n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2**z))))
    s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / 2**z))))
    return w, s, e, n


def tile_range(z: int, bounds: tuple[float, float, float, float]) -> tuple[range, range]:
    w, s, e, n = bounds
    scale = 2**z
    x0, x1 = int((w + 180) / 360 * scale), int((e + 180) / 360 * scale)
    _, py0 = lonlat_to_tile_px(np.array([w]), np.array([n]), z, 0, 0, 1)
    _, py1 = lonlat_to_tile_px(np.array([e]), np.array([s]), z, 0, 0, 1)
    return range(x0, x1 + 1), range(int(py0[0]), int(py1[0]) + 1)


def auto_max_zoom(cell_deg: float, cap: int) -> int:
    """Highest zoom at which a tile pixel is still not much finer than the DEM cell."""
    cell_m = cell_deg * 110_574.0
    for z in range(cap, config.BASEMAP_MIN_ZOOM, -1):
        px_m = 156_543.03 * math.cos(math.radians(38.0)) / 2**z
        if px_m >= cell_m * 0.2:
            return z
    return config.BASEMAP_MIN_ZOOM


# --------------------------------------------------------------------------- water bodies
class Water:
    """Ocean + lake polygons, with a surface elevation per lake."""

    def __init__(self, raw_dir: Path, lon: np.ndarray, lat: np.ndarray, z_ft: np.ndarray):
        bounds = box(*config.BASEMAP_BOUNDS)
        with open(raw_dir / config.NE_OCEAN_NAME, encoding="utf-8") as fh:
            ocean = shape(json.load(fh)["features"][0]["geometry"])
        ocean = ocean if ocean.is_valid else shapely.make_valid(ocean)
        self.ocean_parts = [p for p in getattr(ocean, "geoms", [ocean]) if p.intersects(bounds)]
        self.ocean_tree = STRtree(self.ocean_parts)

        lakes, names = [], []
        for name in config.NE_LAKES_NAMES:
            with open(raw_dir / name, encoding="utf-8") as fh:
                for f in json.load(fh)["features"]:
                    g = shape(f["geometry"])
                    if g.is_empty or not g.intersects(bounds) or g.area < config.MIN_LAKE_AREA:
                        continue
                    g = g if g.is_valid else shapely.make_valid(g)
                    lakes.append(g)
                    p = f["properties"]
                    names.append(p.get("name") or p.get("name_en") or "")
        order = np.argsort([-g.area for g in lakes])        # big first, so inner/small drawn last
        self.lakes = [lakes[i] for i in order]
        self.lake_names = [names[i] for i in order]
        self.lake_tree = STRtree(self.lakes)
        self.lake_level_ft = self._levels(lon, lat, z_ft)

    def _levels(self, lon, lat, z_ft) -> np.ndarray:
        out = np.zeros(len(self.lakes))
        for i, (g, name) in enumerate(zip(self.lakes, self.lake_names)):
            if name in config.LAKE_SURFACE_FT:
                out[i] = config.LAKE_SURFACE_FT[name]
                continue
            w, s, e, n = g.bounds
            step = max(float(lon[1] - lon[0]) / 2, (e - w) / 40)
            gx, gy = np.meshgrid(np.arange(w, e, step), np.arange(s, n, step))
            inside = shapely.contains_xy(g, gx.ravel(), gy.ravel())
            if inside.sum() >= 4:
                v = _point_samples(z_ft, lon, lat, gx.ravel()[inside], gy.ravel()[inside])
                out[i] = np.percentile(v, _SURFACE_PCT)
            else:
                c = g.representative_point()
                out[i] = _point_samples(z_ft, lon, lat, np.array([c.x]), np.array([c.y]))[0]
        return out

    # -- per-tile raster: 0 land, 1 ocean, k >= 2 lake index k-2
    def category(self, z: int, x: int, y: int, n: int) -> np.ndarray:
        w, s, e, nn = tile_bounds_deg(z, x, y)
        pad = (e - w) * 0.02
        window = box(w - pad, s - pad, e + pad, nn + pad)
        img = Image.new("I", (n, n), 0)
        draw = ImageDraw.Draw(img)

        def paint(poly, value):
            clipped = shapely.clip_by_rect(poly, w - pad, s - pad, e + pad, nn + pad)
            for part in getattr(clipped, "geoms", [clipped]):
                if part.is_empty or part.geom_type != "Polygon":
                    continue
                ex = np.asarray(part.exterior.coords)
                px, py = lonlat_to_tile_px(ex[:, 0], ex[:, 1], z, x, y, n)
                draw.polygon(list(zip(px, py)), fill=value)
                for ring in part.interiors:
                    r = np.asarray(ring.coords)
                    rx, ry = lonlat_to_tile_px(r[:, 0], r[:, 1], z, x, y, n)
                    draw.polygon(list(zip(rx, ry)), fill=0)

        for idx in self.ocean_tree.query(window, predicate="intersects"):
            paint(self.ocean_parts[idx], 1)
        for idx in sorted(self.lake_tree.query(window, predicate="intersects")):
            paint(self.lakes[idx], 2 + int(idx))
        return np.asarray(img, dtype=np.int32)


def _point_samples(grid, lon, lat, qlon, qlat) -> np.ndarray:
    ix, fx = _frac_index(lon, qlon)
    iy, fy = _frac_index(lat, qlat)
    return (grid[iy, ix] * (1 - fx) + grid[iy, ix + 1] * fx) * (1 - fy) + \
           (grid[iy + 1, ix] * (1 - fx) + grid[iy + 1, ix + 1] * fx) * fy


# --------------------------------------------------------------------------- renderer
class TileRenderer:
    def __init__(self, raw_dir: Path):
        lon, lat, z_m, self.info = dem.load_dem(raw_dir)
        if lat[0] > lat[-1]:
            lat, z_m = lat[::-1], z_m[::-1]
        self.lon, self.lat = lon, lat
        self.z_ft = z_m.astype(np.float64) * config.FT_PER_M
        hs = config.HILLSHADE
        self.shade = hillshade_grid(lon, lat, z_m, azimuth=hs["azimuth"], altitude=hs["altitude"], zfactor=hs["zfactor"])
        self.flat = math.sin(math.radians(hs["altitude"]))
        self.cell_deg = float(abs(lat[1] - lat[0]))
        self.water = Water(Path(raw_dir), lon, lat, self.z_ft)

    def render(self, z: int, x: int, y: int) -> np.ndarray:
        n = config.TILE_SIZE * SUPERSAMPLE
        qlon, qlat = tile_lonlat(z, x, y, n)
        ft = sample_bilinear(self.z_ft, self.lon, self.lat, qlon, qlat)
        sh = sample_bilinear(self.shade, self.lon, self.lat, qlon, qlat)
        cat = self.water.category(z, x, y, n)

        lake_level = np.concatenate([[0.0, 0.0], self.water.lake_level_ft])[cat]
        depth = np.where(cat == 1, -ft, lake_level - ft)
        is_water = cat > 0

        rgb = apply_ramp(ft, config.LAND_RAMP_FT)
        if is_water.any():
            rgb[is_water] = apply_ramp(np.maximum(depth[is_water], 0.0), config.BATHY_RAMP_FT)

        hs = config.HILLSHADE
        k = np.where(is_water, hs["water_strength"], hs["land_strength"])
        factor = 1.0 + k * (sh / self.flat - 1.0)
        rgb = np.clip(rgb * factor[..., None], 0, 255)

        outside = ((qlon < self.lon[0]) | (qlon > self.lon[-1]))[None, :] | \
                  ((qlat < self.lat[0]) | (qlat > self.lat[-1]))[:, None]
        if outside.any():
            rgb[outside] = NODATA_RGB

        small = rgb.reshape(n // SUPERSAMPLE, SUPERSAMPLE, n // SUPERSAMPLE, SUPERSAMPLE, 3).mean(axis=(1, 3))
        return np.rint(small).astype(np.uint8)


def _save(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(path, "JPEG", quality=config.JPEG_QUALITY, optimize=True)


def build_basemap(raw_dir: Path, out_dir: Path, max_zoom: int | None = None, progress: bool = True) -> dict:
    """Render the tile pyramid into ``out_dir`` and return the metadata the web page needs."""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    r = TileRenderer(raw_dir)
    cap = max_zoom if max_zoom is not None else config.BASEMAP_MAX_ZOOM
    zmax = auto_max_zoom(r.cell_deg, cap) if max_zoom is None else max_zoom
    zmin = min(config.BASEMAP_MIN_ZOOM, zmax)
    if zmax < cap:
        print(f"basemap: DEM cells are {r.cell_deg * 60:.1f} arc-min, so tiles stop at zoom {zmax} "
              "(the map upsamples beyond that); use a finer DEM for more detail")

    if out_dir.exists():
        for old in out_dir.rglob("*.jpg"):
            old.unlink()
    cols, rows = tile_range(zmax, config.BASEMAP_BOUNDS)
    todo = [(x, y) for x in cols for y in rows]
    print(f"basemap: rendering {len(todo)} tiles at zoom {zmax} from {r.info.get('label', 'DEM')} "
          f"({len(r.water.lakes)} lakes)")
    level: dict[tuple[int, int], np.ndarray] = {}
    for i, (x, y) in enumerate(todo, 1):
        arr = r.render(zmax, x, y)
        level[(x, y)] = arr
        _save(arr, out_dir / str(zmax) / str(x) / f"{y}.jpg")
        if progress and (i % 100 == 0 or i == len(todo)):
            print(f"  {i}/{len(todo)}")

    count = len(todo)
    ts = config.TILE_SIZE
    for z in range(zmax - 1, zmin - 1, -1):                      # pyramid by 2x2 averaging
        parents = {(x // 2, y // 2) for (x, y) in level}
        nxt = {}
        for px, py in parents:
            mosaic = np.empty((ts * 2, ts * 2, 3), dtype=np.uint8)
            mosaic[:] = NODATA_RGB
            for dx in (0, 1):
                for dy in (0, 1):
                    child = level.get((px * 2 + dx, py * 2 + dy))
                    if child is not None:
                        mosaic[dy * ts:(dy + 1) * ts, dx * ts:(dx + 1) * ts] = child
            arr = np.rint(mosaic.reshape(ts, 2, ts, 2, 3).mean(axis=(1, 3))).astype(np.uint8)
            nxt[(px, py)] = arr
            _save(arr, out_dir / str(z) / str(px) / f"{py}.jpg")
        level = nxt
        count += len(nxt)

    meta = {
        "minZoom": zmin, "maxZoom": zmax, "tileSize": ts, "bounds": list(config.BASEMAP_BOUNDS),
        "tiles": count, "demLabel": r.info.get("label", "DEM"), "demCellArcmin": round(r.cell_deg * 60, 2),
        "landRamp": ramp_info(config.LAND_RAMP_FT), "bathyRamp": ramp_info(config.BATHY_RAMP_FT),
        "background": "#%02x%02x%02x" % NODATA_RGB,
    }
    (out_dir / "basemap.json").write_text(json.dumps(meta, indent=2))
    print(f"basemap: wrote {count} tiles (zoom {zmin}-{zmax}) to {out_dir}")
    return meta
