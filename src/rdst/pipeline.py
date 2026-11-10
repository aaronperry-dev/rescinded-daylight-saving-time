"""Stage orchestration: fetch -> process -> solar -> build.

Each stage reads the previous stage's files from ``data/`` so any of them can be
re-run on its own. Nothing downloaded is executed; it is only parsed as data.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from . import build, config, fetch, solar, zones


@dataclass
class Paths:
    data_dir: Path = Path("data")
    site_dir: Path = Path("site")

    @property
    def raw(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed(self) -> Path:
        return self.data_dir / "processed"

    @property
    def solar(self) -> Path:
        return self.processed / "solar"

    @property
    def zones_geojson(self) -> Path:
        return self.processed / "conus_zones.geojson"

    @property
    def meta(self) -> Path:
        return self.processed / "meta.json"


def run_fetch(paths: Paths, tz_release: str | None = None, force: bool = False) -> dict:
    return fetch.fetch_all(paths.raw, tz_release=tz_release, force=force)


def run_process(paths: Paths, year: int) -> list:
    manifest_file = paths.raw / "manifest.json"
    if not manifest_file.exists():
        raise SystemExit("No raw data found - run `rdst fetch` first.")
    raw_manifest = json.loads(manifest_file.read_text())
    result = zones.build_conus_zones(paths.raw / config.TZ_ZIP_NAME, paths.raw / config.NE_STATES_NAME, year)

    paths.processed.mkdir(parents=True, exist_ok=True)
    paths.zones_geojson.write_text(json.dumps(zones.to_geojson(result), separators=(",", ":")))
    with open(paths.processed / "zone_rules.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(asdict(result[0][0])))
        w.writeheader()
        w.writerows(asdict(r) for r, _ in result)
    (paths.processed / "conus_states.geojson").write_text(
        json.dumps(zones.build_states(paths.raw / config.NE_STATES_NAME), separators=(",", ":")))
    paths.meta.write_text(json.dumps({
        "year": year,
        "tz_release": raw_manifest["tz_release"],
        "zone_count": len(result),
    }, indent=2))

    print(f"process: kept {len(result)} CONUS zones for {year}:")
    for rule, geom in result:
        dst = f"DST {rule.dst_start} -> {rule.dst_end}" if rule.observes_dst else "no DST"
        print(f"  {rule.tzid:<32} {rule.group:<20} UTC{rule.std_offset:+g}  {dst}")
    return result


def _load_meta(paths: Paths) -> dict:
    if not paths.meta.exists():
        raise SystemExit("No processed data found - run `rdst process` first.")
    return json.loads(paths.meta.read_text())


def run_solar(paths: Paths, res: float = config.FIELD_RESOLUTION) -> dict:
    meta = _load_meta(paths)
    year = meta["year"]
    manifest = solar.build_solar(zones.read_processed(paths.zones_geojson), year, paths.solar, res=res)
    (paths.solar / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def run_build(paths: Paths, with_solar: bool = True) -> Path:
    meta = _load_meta(paths)
    solar_manifest = None
    if with_solar:
        mf = paths.solar / "manifest.json"
        if mf.exists():
            solar_manifest = json.loads(mf.read_text())
        else:
            print("build: no solar rasters found (run `rdst solar`); building without sunrise/sunset layers")
    zone_list = zones.read_processed(paths.zones_geojson)
    return build.build_site(
        paths.site_dir,
        zones_geojson=json.loads(paths.zones_geojson.read_text()),
        states_geojson=json.loads((paths.processed / "conus_states.geojson").read_text()),
        group_labels=zones.group_labels(zone_list),
        year=meta["year"],
        dates=[d.isoformat() for d in config.default_dates(meta["year"])],
        tz_release=meta["tz_release"],
        solar_manifest=solar_manifest,
        solar_dir=paths.solar if solar_manifest else None,
    )


def run_all(paths: Paths, year: int, tz_release: str | None = None, force: bool = False,
            res: float = config.FIELD_RESOLUTION, with_solar: bool = True) -> Path:
    run_fetch(paths, tz_release=tz_release, force=force)
    run_process(paths, year)
    if with_solar:
        run_solar(paths, res=res)
    return run_build(paths, with_solar=with_solar)


def default_year() -> int:
    return date.today().year
