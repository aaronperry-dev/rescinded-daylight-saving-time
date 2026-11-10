"""Stage 4 - assemble the static, self-contained site.

Output layout (open ``site/index.html`` directly or serve the folder):

    index.html  app.js  style.css
    vendor/leaflet/...            (vendored; only map tiles need the network)
    data/data.js                  (zones + metadata, loaded with <script> so file:// works)
    data/solar/<dataset>.js       (sunrise/sunset bands + isochrones, lazy-loaded)
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import config

WEB_DIR = Path(__file__).parent / "web"
_WEB_FILES = ("index.html", "app.js", "style.css")


def build_site(
    site_dir: Path,
    *,
    zones_geojson: dict,
    states_geojson: dict,
    group_labels: list[dict],
    year: int,
    dates: list[str],
    tz_release: str,
    solar_manifest: dict | None,
    solar_dir: Path | None,
) -> Path:
    site_dir = Path(site_dir)
    if site_dir.exists():
        shutil.rmtree(site_dir)
    (site_dir / "data").mkdir(parents=True)

    for name in _WEB_FILES:
        shutil.copy2(WEB_DIR / name, site_dir / name)
    shutil.copytree(WEB_DIR / "vendor", site_dir / "vendor")

    if solar_manifest and solar_dir:
        out = site_dir / "data" / "solar"
        out.mkdir()
        for name in solar_manifest["datasets"]:
            body = (Path(solar_dir) / f"{name}.json").read_text(encoding="utf-8")
            (out / f"{name}.js").write_text(f'RDST_LOAD("{name}",{body});\n', encoding="utf-8")

    payload = {
        "year": year,
        "generatedUtc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "tzRelease": tz_release,
        "scenarios": config.SCENARIOS,
        "scenarioShort": config.SCENARIO_SHORT,
        "offsetRamp": config.OFFSET_RAMP,
        "fallbackColor": config.FALLBACK_COLOR,
        "dates": dates,
        "zones": zones_geojson,
        "states": states_geojson,
        "groupLabels": group_labels,
        "solar": solar_manifest,
    }
    (site_dir / "data" / "data.js").write_text(
        "window.RDST = " + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8"
    )
    size = sum(p.stat().st_size for p in site_dir.rglob("*") if p.is_file()) / 1e6
    print(f"build: wrote {site_dir}/ ({size:.1f} MB). Open {site_dir / 'index.html'}")
    return site_dir / "index.html"
