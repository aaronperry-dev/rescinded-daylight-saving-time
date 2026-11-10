"""Digital elevation model access: ETOPO 2022 (NOAA, via OPeNDAP) or a coarse GitHub-hosted fallback.

Both return elevation in **metres above sea level** (negative = bathymetry) on a regular
lon/lat grid, which is cached as ``data/raw/dem.npz`` so the basemap stage runs offline.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import requests

from . import config

_LON_NAMES = ("lon", "longitude", "x")
_LAT_NAMES = ("lat", "latitude", "y")
_Z_NAMES = ("z", "elevation", "topography", "height", "elev", "depth")


def dem_bounds() -> tuple[float, float, float, float]:
    w, s, e, n = config.BASEMAP_BOUNDS
    m = config.DEM_MARGIN
    return w - m, s - m, e + m, n + m


def _pick(names: tuple[str, ...], available) -> str:
    low = {k.lower(): k for k in available}
    for n in names:
        if n in low:
            return low[n]
    raise KeyError(f"none of {names} found in {sorted(available)}")


def read_netcdf_subset(path_or_url: str, bounds: tuple[float, float, float, float]):
    """Read the lon/lat window ``bounds`` (w, s, e, n) from a NetCDF file or OPeNDAP URL.

    Coordinate arrays are read in full (they are 1-D and small); only the requested window of the
    elevation variable is transferred, which is what makes the OPeNDAP route practical.
    Returns ``(lon, lat, z)`` with ascending lon/lat and ``z`` as float32 metres.
    """
    import netCDF4  # imported lazily so the rest of the pipeline works without it

    w, s, e, n = bounds
    with netCDF4.Dataset(path_or_url) as ds:
        lon_name = _pick(_LON_NAMES, ds.variables)
        lat_name = _pick(_LAT_NAMES, ds.variables)
        z_name = _pick(_Z_NAMES, ds.variables)
        lon = np.asarray(ds.variables[lon_name][:], dtype=np.float64)
        lat = np.asarray(ds.variables[lat_name][:], dtype=np.float64)
        var = ds.variables[z_name]
        if var.dimensions != (lat_name, lon_name):
            raise ValueError(f"expected {z_name}({lat_name}, {lon_name}); got {var.dimensions}")

        i0, i1 = int(np.searchsorted(lon, w) - 1), int(np.searchsorted(lon, e) + 1)
        flip = lat[0] > lat[-1]
        lat_asc = lat[::-1] if flip else lat
        j0, j1 = int(np.searchsorted(lat_asc, s) - 1), int(np.searchsorted(lat_asc, n) + 1)
        i0, j0 = max(i0, 0), max(j0, 0)
        i1, j1 = min(i1, lon.size), min(j1, lat.size)
        if i1 - i0 < 2 or j1 - j0 < 2:
            raise ValueError(f"requested window {bounds} is outside the dataset")
        if flip:  # translate ascending-lat indices back to file order
            fj0, fj1 = lat.size - j1, lat.size - j0
            block = np.ma.filled(var[fj0:fj1, i0:i1].astype("float32"), np.nan)[::-1]
            lat_out = lat[fj0:fj1][::-1]
        else:
            block = np.ma.filled(var[j0:j1, i0:i1].astype("float32"), np.nan)
            lat_out = lat[j0:j1]
    return lon[i0:i1], lat_out, block


def _check(z: np.ndarray) -> None:
    if not np.isfinite(z).all():
        raise ValueError("DEM contains missing values inside the requested window")
    if z.min() > -50 or z.max() < 500:
        raise ValueError("DEM values do not look like metres with bathymetry "
                         f"(min {z.min():.0f}, max {z.max():.0f})")


def fetch_dem(raw_dir: Path, source: str, resolution: str = "60s") -> dict:
    """Download (or subset) the DEM for the basemap extent into ``raw_dir/dem.npz``."""
    raw_dir = Path(raw_dir)
    bounds = dem_bounds()
    if source == "etopo2022":
        if resolution not in config.ETOPO2022_RESOLUTIONS:
            raise ValueError(f"resolution must be one of {config.ETOPO2022_RESOLUTIONS}")
        url = config.ETOPO2022_OPENDAP.format(res=resolution)
        print(f"fetch: ETOPO 2022 {resolution} via OPeNDAP (subset only; first access can take a minute)")
        try:
            lon, lat, z = read_netcdf_subset(url, bounds)
        except (OSError, RuntimeError) as err:
            raise RuntimeError(
                f"Could not read ETOPO 2022 from {url}: {err}\n"
                "Check your connection, or use `--dem etopo10` (coarse, GitHub-hosted), or download an "
                "ETOPO 2022 NetCDF yourself and pass it with `--dem-file path/to.nc`.") from err
        label = f"ETOPO 2022 {resolution} (NOAA NCEI)"
    elif source == "etopo10":
        nc = raw_dir / "earth-topography-10arcmin.nc"
        print("fetch: ETOPO1 10 arc-minute grid (coarse fallback, GitHub release)")
        if not nc.exists():
            with requests.get(config.ETOPO10_URL, stream=True, timeout=(15, 120)) as r:
                r.raise_for_status()
                nc.write_bytes(r.content)
        lon, lat, z = read_netcdf_subset(str(nc), bounds)
        url, label = config.ETOPO10_URL, "ETOPO1 10 arc-minute (NOAA NCEI via fatiando-data) - coarse"
    else:
        raise ValueError(f"unknown DEM source {source!r}; choose from {config.DEM_SOURCES}")
    return save_dem(raw_dir, lon, lat, z, {"source": source, "label": label, "url": url, "resolution": resolution})


def use_dem_file(raw_dir: Path, path: str) -> dict:
    lon, lat, z = read_netcdf_subset(path, dem_bounds())
    return save_dem(Path(raw_dir), lon, lat, z, {"source": "file", "label": f"user file {Path(path).name}", "url": str(path)})


def save_dem(raw_dir: Path, lon, lat, z, info: dict) -> dict:
    _check(z)
    raw_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(raw_dir / config.DEM_FILE_NAME, lon=lon, lat=lat, z=z)
    info = {**info, "cells": [int(z.shape[1]), int(z.shape[0])],
            "cell_deg": [float(abs(lon[1] - lon[0])), float(abs(lat[1] - lat[0]))]}
    (raw_dir / "dem.json").write_text(json.dumps(info, indent=2))
    print(f"fetch: DEM {z.shape[1]}x{z.shape[0]} cells, {z.min():.0f}..{z.max():.0f} m -> {config.DEM_FILE_NAME}")
    return info


def load_dem(raw_dir: Path):
    """Return ``(lon, lat, z, info)`` from the cached DEM."""
    raw_dir = Path(raw_dir)
    f = raw_dir / config.DEM_FILE_NAME
    if not f.exists():
        raise SystemExit("No DEM found - run `rdst fetch` (or `rdst fetch --dem etopo10`) first.")
    d = np.load(f)
    info = json.loads((raw_dir / "dem.json").read_text()) if (raw_dir / "dem.json").exists() else {}
    return d["lon"], d["lat"], d["z"], info
