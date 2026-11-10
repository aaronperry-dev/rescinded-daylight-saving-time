"""Command line entry point: ``rdst <stage>`` or ``python -m rdst <stage>``."""
from __future__ import annotations

import argparse
from pathlib import Path

from . import config, pipeline


def _dem_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dem", choices=config.DEM_SOURCES, default="etopo2022",
                   help="elevation/bathymetry source: etopo2022 (NOAA, sharp, default) or etopo10 (coarse 10 arc-min)")
    p.add_argument("--dem-resolution", choices=config.ETOPO2022_RESOLUTIONS, default="60s",
                   help="ETOPO 2022 grid: 60s (~1.8 km, ~45 MB) or 30s (~0.9 km, ~170 MB)")
    p.add_argument("--dem-file", help="use your own NetCDF elevation grid (metres, lat/lon) instead of downloading")


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", type=Path, default=Path("data"), help="intermediate files (default: ./data)")
    common.add_argument("--site-dir", type=Path, default=Path("site"), help="built website (default: ./site)")

    p = argparse.ArgumentParser(prog="rdst", description=__doc__)
    sub = p.add_subparsers(dest="stage", required=True)

    f = sub.add_parser("fetch", parents=[common], help="download boundary data")
    f.add_argument("--tz-release", help="pin a timezone-boundary-builder tag, e.g. 2026f (default: latest)")
    f.add_argument("--force", action="store_true", help="re-download even if cached")
    f.add_argument("--no-dem", action="store_true", help="skip the elevation grid (basemap stage then unavailable)")
    _dem_args(f)

    pr = sub.add_parser("process", parents=[common], help="clip zones to CONUS and derive DST rules")
    pr.add_argument("--year", type=int, default=pipeline.default_year(), help="rules year (default: current year)")

    bm = sub.add_parser("basemap", parents=[common], help="render the terrain + bathymetry tile pyramid")
    bm.add_argument("--max-zoom", type=int, help="finest tile zoom (default: chosen from the DEM resolution, max 7)")

    s = sub.add_parser("solar", parents=[common], help="render sunrise/sunset clock-time rasters")
    s.add_argument("--res", type=float, default=config.FIELD_RESOLUTION, help="contour node spacing in degrees")

    b = sub.add_parser("build", parents=[common], help="assemble the static site")
    b.add_argument("--no-solar", action="store_true", help="omit the sunrise/sunset layers")

    a = sub.add_parser("all", parents=[common], help="run every stage")
    a.add_argument("--year", type=int, default=pipeline.default_year())
    a.add_argument("--tz-release")
    a.add_argument("--force", action="store_true")
    a.add_argument("--res", type=float, default=config.FIELD_RESOLUTION)
    a.add_argument("--no-solar", action="store_true")
    a.add_argument("--max-zoom", type=int)
    _dem_args(a)
    return p


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    paths = pipeline.Paths(data_dir=args.data_dir, site_dir=args.site_dir)
    if args.stage == "fetch":
        pipeline.run_fetch(paths, tz_release=args.tz_release, force=args.force, dem=args.dem,
                           dem_resolution=args.dem_resolution, dem_file=args.dem_file, with_dem=not args.no_dem)
    elif args.stage == "process":
        pipeline.run_process(paths, args.year)
    elif args.stage == "basemap":
        pipeline.run_basemap(paths, max_zoom=args.max_zoom)
    elif args.stage == "solar":
        pipeline.run_solar(paths, res=args.res)
    elif args.stage == "build":
        pipeline.run_build(paths, with_solar=not args.no_solar)
    else:
        pipeline.run_all(paths, args.year, tz_release=args.tz_release, force=args.force,
                         res=args.res, with_solar=not args.no_solar, dem=args.dem,
                         dem_resolution=args.dem_resolution, dem_file=args.dem_file, max_zoom=args.max_zoom)


if __name__ == "__main__":
    main()
