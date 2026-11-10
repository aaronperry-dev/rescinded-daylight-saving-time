"""Basemap: colour ramps in feet, tile maths, hillshade, DEM reading and the tile pyramid (no network)."""
import json
import math

import numpy as np
import pytest
from shapely.geometry import box, mapping

from rdst import basemap, build, config, dem


# --------------------------------------------------------------------------- ramps / maths
def test_ramps_hit_their_stops_and_are_monotone_in_the_expected_direction():
    land = basemap.apply_ramp(np.array([s[0] for s in config.LAND_RAMP_FT], float), config.LAND_RAMP_FT)
    assert [tuple(map(int, c)) for c in land] == [basemap._hex_rgb(s[1]) for s in config.LAND_RAMP_FT]
    # beyond the ends the colour is clamped, not extrapolated
    assert tuple(basemap.apply_ramp(np.array([1e6]), config.LAND_RAMP_FT)[0]) == basemap._hex_rgb(config.LAND_RAMP_FT[-1][1])
    # water gets darker with depth
    depths = np.array([s[0] for s in config.BATHY_RAMP_FT], float)
    lum = basemap.apply_ramp(depths, config.BATHY_RAMP_FT).sum(axis=1)
    assert np.all(np.diff(lum) < 0)
    # stops are ascending
    for ramp in (config.LAND_RAMP_FT, config.BATHY_RAMP_FT):
        xs = [s[0] for s in ramp]
        assert xs == sorted(xs) and len(set(xs)) == len(xs)


def test_tile_pixel_maths_round_trips():
    z, x, y = 6, 17, 26
    w, s, e, n = basemap.tile_bounds_deg(z, x, y)
    px, py = basemap.lonlat_to_tile_px(np.array([w, e, w, e]), np.array([n, n, s, s]), z, x, y, 256)
    assert np.allclose(px, [0, 256, 0, 256], atol=1e-6) and np.allclose(py, [0, 0, 256, 256], atol=1e-6)
    lon, lat = basemap.tile_lonlat(z, x, y, 256)
    assert w < lon[0] < lon[-1] < e and n > lat[0] > lat[-1] > s     # lat decreases down the image


def test_tile_range_covers_bounds():
    cols, rows = basemap.tile_range(5, (-100, 30, -90, 40))
    w, _, _, n = basemap.tile_bounds_deg(5, cols[0], rows[0])
    _, s, e, _ = basemap.tile_bounds_deg(5, cols[-1], rows[-1])
    assert w <= -100 and e >= -90 and n >= 40 and s <= 30         # the tiles enclose the bounds
    # no wholly-unneeded tile at the start of the range
    _, _, e0, _ = basemap.tile_bounds_deg(5, cols[0], rows[0])
    assert e0 > -100


def test_auto_max_zoom_follows_dem_resolution():
    assert basemap.auto_max_zoom(1 / 60, 7) == 7           # ETOPO 60 arc-sec -> full detail
    assert basemap.auto_max_zoom(10 / 60, 7) < 7           # coarse fallback stops early
    assert basemap.auto_max_zoom(0.001, 7) == 7            # never exceeds the cap


def test_hillshade_lights_slopes_that_face_the_sun():
    lon = np.linspace(-100, -99, 41)
    lat = np.linspace(30, 31, 41)
    xx, _ = np.meshgrid(lon, lat)
    kw = dict(azimuth=315.0, altitude=42.0, zfactor=4.0)
    flat = basemap.hillshade_grid(lon, lat, np.zeros_like(xx), **kw)
    assert flat == pytest.approx(math.sin(math.radians(42)), abs=1e-6)
    rising_east = basemap.hillshade_grid(lon, lat, (xx + 100) * 20000, **kw)    # faces west, toward the NW sun
    rising_west = basemap.hillshade_grid(lon, lat, -(xx + 100) * 20000, **kw)   # faces east, away from it
    assert rising_east[20, 20] > flat[20, 20] > rising_west[20, 20]


def test_bilinear_sampling_is_exact_on_a_plane():
    lon = np.linspace(0, 10, 11)
    lat = np.linspace(0, 5, 6)
    grid = 3 * lon[None, :] + 7 * lat[:, None]
    q_lon, q_lat = np.array([0.5, 2.25, 9.9]), np.array([0.1, 4.4])
    out = basemap.sample_bilinear(grid, lon, lat, q_lon, q_lat)
    assert out == pytest.approx(3 * q_lon[None, :] + 7 * q_lat[:, None])


# --------------------------------------------------------------------------- DEM reading
def _write_nc(path, lon, lat, z, names=("lon", "lat", "z"), flip=False):
    import netCDF4
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension(names[1], lat.size)
        ds.createDimension(names[0], lon.size)
        ds.createVariable(names[0], "f8", (names[0],))[:] = lon
        ds.createVariable(names[1], "f8", (names[1],))[:] = lat[::-1] if flip else lat
        ds.createVariable(names[2], "f4", (names[1], names[0]))[:] = z[::-1] if flip else z


@pytest.mark.parametrize("names,flip", [(("lon", "lat", "z"), False), (("longitude", "latitude", "topography"), True)])
def test_read_netcdf_subset_handles_names_and_latitude_order(tmp_path, names, flip):
    lon, lat = np.arange(-110.0, -70.0, 0.5), np.arange(20.0, 50.0, 0.5)
    z = (lon[None, :] + 200) * 10 + lat[:, None]                      # unique, smooth, lon/lat recoverable
    f = tmp_path / "d.nc"
    _write_nc(f, lon, lat, z.astype("f4"), names, flip)
    lo, la, zz = dem.read_netcdf_subset(str(f), (-100, 30, -90, 40))
    assert np.all(np.diff(lo) > 0) and np.all(np.diff(la) > 0)
    assert lo[0] <= -100 and lo[-1] >= -90 and la[0] <= 30 and la[-1] >= 40
    assert zz == pytest.approx((lo[None, :] + 200) * 10 + la[:, None], abs=1e-3)


def test_read_netcdf_subset_rejects_a_window_outside_the_data(tmp_path):
    lon, lat = np.arange(0.0, 10.0, 0.5), np.arange(0.0, 10.0, 0.5)
    _write_nc(tmp_path / "d.nc", lon, lat, np.zeros((lat.size, lon.size), "f4"))
    with pytest.raises(ValueError, match="outside"):
        dem.read_netcdf_subset(str(tmp_path / "d.nc"), (-100, 30, -90, 40))


def test_dem_sanity_check_rejects_data_without_bathymetry():
    with pytest.raises(ValueError, match="bathymetry"):
        dem._check(np.full((4, 4), 100.0, dtype="f4"))


# --------------------------------------------------------------------------- tiles
@pytest.fixture()
def synthetic_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASEMAP_BOUNDS", (-100.0, 30.0, -90.0, 40.0))
    raw = tmp_path / "raw"
    raw.mkdir()
    lon, lat = np.arange(-100.5, -89.49, 0.05), np.arange(29.5, 40.51, 0.05)
    xx, yy = np.meshgrid(lon, lat)
    ft = np.full(xx.shape, 1000.0)
    ocean = (xx < -96) & (yy < 34)
    ft[ocean] = -1000.0
    ft[(xx < -100.2) & (yy > 39)] = 4000.0                              # outside the tile area; keeps the DEM sanity check happy
    lake = (xx > -93) & (xx < -91) & (yy > 36) & (yy < 38)
    r = np.hypot(xx + 92, yy - 37)
    ft[lake] = 800.0 + 200.0 * np.clip(r[lake], 0, 1)                 # bowl: 800 ft deep centre -> 1000 ft rim
    dem.save_dem(raw, lon, lat, (ft / config.FT_PER_M).astype("f4"), {"source": "synthetic", "label": "synthetic DEM"})

    fc = lambda g, **p: {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": p, "geometry": mapping(g)}]}
    (raw / config.NE_OCEAN_NAME).write_text(json.dumps(fc(box(-101, 29, -96, 34))))
    (raw / config.NE_LAKES_NAMES[0]).write_text(json.dumps(fc(box(-93, 36, -91, 38), name="Test Lake")))
    (raw / config.NE_LAKES_NAMES[1]).write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    return raw


def _px(arr, lon, lat, z, x, y):
    px, py = basemap.lonlat_to_tile_px(np.array([lon]), np.array([lat]), z, x, y, 256)
    return arr[int(py[0]), int(px[0])].astype(int)


def test_tile_colours_follow_land_ocean_and_lake_semantics(synthetic_raw):
    r = basemap.TileRenderer(synthetic_raw)
    z = 6
    cols, rows = basemap.tile_range(z, config.BASEMAP_BOUNDS)
    tiles = {(x, y): r.render(z, x, y) for x in cols for y in rows}

    def at(lon, lat):
        x = int((lon + 180) / 360 * 2**z)
        py = basemap.lonlat_to_tile_px(np.array([lon]), np.array([lat]), z, 0, 0, 256)[1][0] / 256
        return _px(tiles[(x, int(py))], lon, lat, z, x, int(py))

    ocean, lake, land = at(-98, 32), at(-92, 37), at(-95, 38.5)
    assert ocean[2] > ocean[0] + 30 and lake[2] > lake[0] + 15          # blue water
    assert land[1] > land[2] and land[0] > land[2]                        # yellow-green land, not blue
    assert ocean.sum() < lake.sum()                                       # 1000 ft of ocean is darker than a 200 ft lake


def test_lake_surface_uses_the_dem_rim_not_sea_level(synthetic_raw):
    w = basemap.Water(synthetic_raw, *dem.load_dem(synthetic_raw)[:2],
                      dem.load_dem(synthetic_raw)[2].astype(float) * config.FT_PER_M)
    assert len(w.lakes) == 1
    assert 950 < w.lake_level_ft[0] <= 1000.5            # 95th percentile of the bowl ~ its rim


def test_named_lake_surface_override_wins(synthetic_raw, monkeypatch):
    monkeypatch.setitem(config.LAKE_SURFACE_FT, "Test Lake", 1234.0)
    lon, lat, z, _ = dem.load_dem(synthetic_raw)
    w = basemap.Water(synthetic_raw, lon, lat, z.astype(float) * config.FT_PER_M)
    assert w.lake_level_ft[0] == 1234.0


def test_pyramid_is_complete_and_metadata_describes_it(synthetic_raw, tmp_path):
    out = tmp_path / "tiles"
    meta = basemap.build_basemap(synthetic_raw, out, max_zoom=5, progress=False)
    assert meta["maxZoom"] == 5 and meta["minZoom"] == 3
    for z in range(3, 6):
        files = list((out / str(z)).rglob("*.jpg"))
        assert files, z
        assert all(p.stat().st_size > 100 for p in files)
    # every z<5 tile has a parent chain: tile (x, y) at z implies (x//2, y//2) at z-1
    have = {(z, int(p.parent.name), int(p.stem)) for z in range(3, 6) for p in (out / str(z)).rglob("*.jpg")}
    for z, x, y in have:
        if z > 3:
            assert (z - 1, x // 2, y // 2) in have
    on_disk = json.loads((out / "basemap.json").read_text())
    assert on_disk["tiles"] == len(have) == meta["tiles"]
    assert [s["ft"] for s in on_disk["landRamp"]] == [s[0] for s in config.LAND_RAMP_FT]
    from PIL import Image
    assert Image.open(next((out / "5").rglob("*.jpg"))).size == (256, 256)


def test_build_site_copies_tiles_and_exposes_basemap_metadata(synthetic_raw, tmp_path):
    tiles = tmp_path / "tiles"
    meta = basemap.build_basemap(synthetic_raw, tiles, max_zoom=4, progress=False)
    fc = {"type": "FeatureCollection", "features": []}
    index = build.build_site(tmp_path / "site", zones_geojson=fc, boundaries_geojson=fc, zone_borders_geojson=fc, state_labels=[], group_labels=[],
                             year=2026, dates=["2026-07-01"], tz_release="t", solar_manifest=None, solar_dir=None,
                             basemap_meta=meta, tiles_dir=tiles)
    site = index.parent
    assert list((site / "tiles").rglob("*.jpg")) and not (site / "tiles" / "basemap.json").exists()
    assert '"basemap":{' in (site / "data" / "data.js").read_text()
