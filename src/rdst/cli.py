"""Command line entry point: ``rdst <stage>`` or ``python -m rdst <stage>``."""
from __future__ import annotations

import argparse
from pathlib import Path

from . import config, pipeline


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", type=Path, default=Path("data"), help="intermediate files (default: ./data)")
    common.add_argument("--site-dir", type=Path, default=Path("site"), help="built website (default: ./site)")

    p = argparse.ArgumentParser(prog="rdst", description=__doc__)
    sub = p.add_subparsers(dest="stage", required=True)

    f = sub.add_parser("fetch", parents=[common], help="download boundary data")
    f.add_argument("--tz-release", help="pin a timezone-boundary-builder tag, e.g. 2026f (default: latest)")
    f.add_argument("--force", action="store_true", help="re-download even if cached")

    pr = sub.add_parser("process", parents=[common], help="clip zones to CONUS and derive DST rules")
    pr.add_argument("--year", type=int, default=pipeline.default_year(), help="rules year (default: current year)")

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
    return p


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    paths = pipeline.Paths(data_dir=args.data_dir, site_dir=args.site_dir)
    if args.stage == "fetch":
        pipeline.run_fetch(paths, tz_release=args.tz_release, force=args.force)
    elif args.stage == "process":
        pipeline.run_process(paths, args.year)
    elif args.stage == "solar":
        pipeline.run_solar(paths, res=args.res)
    elif args.stage == "build":
        pipeline.run_build(paths, with_solar=not args.no_solar)
    else:
        pipeline.run_all(paths, args.year, tz_release=args.tz_release, force=args.force,
                         res=args.res, with_solar=not args.no_solar)


if __name__ == "__main__":
    main()
