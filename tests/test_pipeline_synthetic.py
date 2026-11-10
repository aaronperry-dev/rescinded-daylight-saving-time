"""End-to-end run of process -> solar -> build on tiny synthetic inputs (no network)."""
import json
import re
import zipfile

import pytest
import shapely
from shapely.geometry import box, mapping

from rdst import build, config, pipeline, zones


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


@pytest.fixture()
def paths(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    # two "states" tiling lon -100..-80, lat 30..40; AK must be ignored
    states = _fc([
        {"type": "Feature", "properties": {"adm0_a3": "USA", "postal": "AA"}, "geometry": mapping(box(-100, 30, -90, 40))},
        {"type": "Feature", "properties": {"adm0_a3": "USA", "postal": "BB"}, "geometry": mapping(box(-90, 30, -80, 40))},
        {"type": "Feature", "properties": {"adm0_a3": "USA", "postal": "AK"}, "geometry": mapping(box(-160, 60, -150, 65))},
        {"type": "Feature", "properties": {"adm0_a3": "CAN", "postal": "ON"}, "geometry": mapping(box(-100, 40, -80, 45))},
    ])
    (raw / config.NE_STATES_NAME).write_text(json.dumps(states))
    # zones: Chicago west half, New York east half, plus a Canadian zone that overlaps by a sliver
    zone_fc = _fc([
        {"type": "Feature", "properties": {"tzid": "America/Chicago"}, "geometry": mapping(box(-101, 29, -90, 41))},
        {"type": "Feature", "properties": {"tzid": "America/New_York"}, "geometry": mapping(box(-90, 29, -79, 41))},
        {"type": "Feature", "properties": {"tzid": "America/Toronto"}, "geometry": mapping(box(-100, 39.9, -80, 50))},
        {"type": "Feature", "properties": {"tzid": "Europe/Paris"}, "geometry": mapping(box(0, 40, 5, 45))},
    ])
    with zipfile.ZipFile(raw / config.TZ_ZIP_NAME, "w") as z:
        z.writestr("combined.json", json.dumps(zone_fc))
    (raw / "manifest.json").write_text(json.dumps({"tz_release": "test", "files": {}}))
    return pipeline.Paths(data_dir=tmp_path / "data", site_dir=tmp_path / "site")


def test_process_keeps_only_us_zones_clipped_to_the_mask(paths):
    result = pipeline.run_process(paths, 2026)
    assert sorted(r.tzid for r, _ in result) == ["America/Chicago", "America/New_York"]
    mask = box(-100, 30, -80, 40)
    for _, g in result:
        assert g.within(mask.buffer(1e-6))
    union = shapely.union_all([g for _, g in result])
    assert union.area == pytest.approx(mask.area, rel=1e-3)  # no gaps from simplification
    assert (paths.processed / "zone_rules.csv").exists()
    assert json.loads((paths.processed / "conus_states.geojson").read_text())["features"]
    states = {f["properties"]["postal"] for f in json.loads((paths.processed / "conus_states.geojson").read_text())["features"]}
    assert states == {"AA", "BB"}


def test_full_pipeline_builds_a_working_site(paths):
    pipeline.run_process(paths, 2026)
    manifest = pipeline.run_solar(paths, res=0.5)
    assert len(manifest["datasets"]) == 2 * 2 * 3
    # only cities whose zone exists in the data are listed (Phoenix/Denver/LA/Seattle are absent here)
    assert set(manifest["cities"]) == {"Minneapolis", "Dallas", "Chicago", "Atlanta", "New York", "Miami"}

    index = pipeline.run_build(paths)
    site = index.parent
    for name in ("index.html", "app.js", "style.css", "vendor/leaflet/leaflet.js", "data/data.js"):
        assert (site / name).exists(), name

    payload = json.loads(re.match(r"window\.RDST = (.*);\s*$", (site / "data" / "data.js").read_text(), re.S).group(1))
    assert payload["year"] == 2026 and payload["tzRelease"] == "test"
    assert set(payload["scenarios"]) == {config.CURRENT, config.RESCINDED, config.PERMANENT}
    assert len(payload["zones"]["features"]) == 2
    assert {g["text"] for g in payload["groupLabels"]} == {"CENTRAL", "EASTERN"}

    for key in payload["solar"]["datasets"]:
        js = (site / "data" / "solar" / f"{key}.js").read_text()
        assert js.startswith(f'RDST_LOAD("{key}",')
        body = json.loads(js[len(f'RDST_LOAD("{key}",'):].rstrip().rstrip(";").rstrip(")"))
        assert body["bands"]["features"], key
        assert "lines" in body and "labels" in body and "cities" in body

    # rescinding DST moves the summer sunset back an hour in both zones
    cur = json.loads((paths.solar / "sunset_latest_current.json").read_text())["cities"]
    res = json.loads((paths.solar / "sunset_latest_rescinded.json").read_text())["cities"]
    assert cur and all(cur[c] - res[c] == pytest.approx(60) for c in cur)


def test_build_without_solar_omits_sunrise_sunset(paths):
    pipeline.run_process(paths, 2026)
    index = pipeline.run_build(paths, with_solar=False)
    assert not (index.parent / "data" / "solar").exists()
    assert "window.RDST" in (index.parent / "data" / "data.js").read_text()
    assert '"solar":null' in (index.parent / "data" / "data.js").read_text()


def test_coverage_simplification_keeps_shared_borders():
    a, b = box(0, 0, 1, 1).buffer(0), box(1, 0, 2, 1).buffer(0)
    out = zones.simplify_coverage({"a": a, "b": b}, 0.01)
    assert shapely.union_all(list(out.values())).area == pytest.approx(2.0)
    assert out["a"].intersection(out["b"]).length == pytest.approx(1.0)


def test_missing_raw_data_gives_a_helpful_error(tmp_path):
    with pytest.raises(SystemExit, match="rdst fetch"):
        pipeline.run_process(pipeline.Paths(tmp_path / "d", tmp_path / "s"), 2026)


def test_build_site_clears_stale_output(tmp_path):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "stale.txt").write_text("x")
    build.build_site(site, zones_geojson=_fc([]), states_geojson=_fc([]), group_labels=[], year=2026,
                     dates=["2026-07-01"], tz_release="t", solar_manifest=None, solar_dir=None)
    assert not (site / "stale.txt").exists()
