from datetime import date

import numpy as np
import pytest

from rdst import config, solar
from rdst.zones import compute_rule, group_name

YEAR = 2026


# ------------------------------------------------------------------ DST rules
def test_new_york_rule_matches_us_law():
    r = compute_rule("America/New_York", YEAR)
    assert (r.std_offset, r.dst_offset, r.observes_dst) == (-5.0, -4.0, True)
    assert (r.dst_start, r.dst_end) == ("2026-03-08", "2026-10-31")  # 2nd Sun Mar .. day before 1st Sun Nov
    assert (r.std_abbr, r.dst_abbr, r.group) == ("EST", "EDT", "Eastern")


def test_phoenix_never_changes():
    r = compute_rule("America/Phoenix", YEAR)
    assert not r.observes_dst
    assert r.std_offset == r.dst_offset == -7.0
    assert r.group == "Mountain (no DST)"
    for scen in config.SCENARIOS:
        assert r.offset_on(date(2026, 7, 1), scen) == -7.0


@pytest.mark.parametrize("tzid,summer,winter", [
    ("America/Chicago", -5, -6), ("America/Denver", -6, -7), ("America/Los_Angeles", -7, -8),
])
def test_scenario_offsets(tzid, summer, winter):
    r = compute_rule(tzid, YEAR)
    jul, jan = date(2026, 7, 1), date(2026, 1, 15)
    assert r.offset_on(jul, config.CURRENT) == summer
    assert r.offset_on(jan, config.CURRENT) == winter
    assert r.offset_on(jul, config.RESCINDED) == r.offset_on(jan, config.RESCINDED) == winter
    assert r.offset_on(jul, config.PERMANENT) == r.offset_on(jan, config.PERMANENT) == summer


def test_dst_boundaries_are_inclusive():
    r = compute_rule("America/New_York", YEAR)
    assert not r.dst_active(date(2026, 3, 7))
    assert r.dst_active(date(2026, 3, 8))
    assert r.dst_active(date(2026, 10, 31))
    assert not r.dst_active(date(2026, 11, 1))


def test_unknown_scenario_raises():
    with pytest.raises(ValueError):
        compute_rule("America/Chicago", YEAR).offset_on(date(2026, 7, 1), "nope")


def test_group_name():
    assert group_name(-5.0, True) == "Eastern"
    assert group_name(-8.0, False) == "Pacific (no DST)"


# ---------------------------------------------------------------------- solar
# Reference sunrise/sunset in local clock minutes (timeanddate / NOAA calculator).
REFERENCE = [
    # name, lat, lon, date, utc offset, sunrise, sunset
    ("New York Jun 21", 40.7128, -74.0060, date(2026, 6, 21), -4, 5 * 60 + 25, 20 * 60 + 31),
    ("Chicago Jun 21", 41.8781, -87.6298, date(2026, 6, 21), -5, 5 * 60 + 15, 20 * 60 + 29),
    ("Denver Jun 21", 39.7392, -104.9903, date(2026, 6, 21), -6, 5 * 60 + 32, 20 * 60 + 31),
    ("Los Angeles Jun 21", 34.0522, -118.2437, date(2026, 6, 21), -7, 5 * 60 + 42, 20 * 60 + 8),
    ("New York Dec 21", 40.7128, -74.0060, date(2026, 12, 21), -5, 7 * 60 + 17, 16 * 60 + 32),
]


@pytest.mark.parametrize("name,lat,lon,day,off,rise,sett", REFERENCE, ids=[r[0] for r in REFERENCE])
def test_sun_events_match_reference(name, lat, lon, day, off, rise, sett):
    r, s = solar.sun_events_utc_minutes(lat, lon, day)
    assert abs((r + 60 * off) % 1440 - rise) <= 3
    assert abs((s + 60 * off) % 1440 - sett) <= 3


def _extremes(tzid, lat, lon):
    rule = compute_rule(tzid, YEAR)
    out = solar.annual_extremes(rule, np.array([lat]), np.array([lon]), YEAR)
    return {k: float(v[0]) for k, v in out.items()}


def test_rescinding_dst_moves_summer_extremes_back_exactly_one_hour():
    e = _extremes("America/New_York", 40.71, -74.01)
    assert e[("sunset", "latest", config.RESCINDED)] == pytest.approx(e[("sunset", "latest", config.CURRENT)] - 60)
    assert e[("sunrise", "earliest", config.RESCINDED)] == pytest.approx(e[("sunrise", "earliest", config.CURRENT)] - 60)


def test_earliest_sunset_is_identical_under_current_and_rescinded():
    # DST days only ever have later sunsets, so the winter minimum is the same either way.
    e = _extremes("America/New_York", 40.71, -74.01)
    assert e[("sunset", "earliest", config.CURRENT)] == pytest.approx(e[("sunset", "earliest", config.RESCINDED)])


def test_latest_sunrise_differs_by_minutes_not_an_hour_between_current_and_rescinded():
    # Under current law the latest sunrise is the morning of the March clock change (7:2x AM in
    # New York), a few minutes later than the January maximum that rescinding leaves in place.
    e = _extremes("America/New_York", 40.71, -74.01)
    gap = e[("sunrise", "latest", config.CURRENT)] - e[("sunrise", "latest", config.RESCINDED)]
    assert 0 <= gap < 30


def test_permanent_dst_adds_an_hour_to_every_rescinded_extreme():
    e = _extremes("America/Chicago", 41.88, -87.63)
    for metric in solar.METRICS:
        for stat in solar.STATS:
            assert e[(metric, stat, config.PERMANENT)] == pytest.approx(e[(metric, stat, config.RESCINDED)] + 60)


def test_latest_sunrise_under_current_law_can_be_after_the_spring_change():
    # Los Angeles: the latest current-law sunrise is the day after the March change, so
    # permanent DST (which adds a full hour to the January sunrise) moves it by < 60 min.
    e = _extremes("America/Los_Angeles", 34.05, -118.24)
    shift = e[("sunrise", "latest", config.PERMANENT)] - e[("sunrise", "latest", config.CURRENT)]
    assert 30 < shift < 60


def test_arizona_is_unchanged_by_rescinding():
    e = _extremes("America/Phoenix", 33.45, -112.07)
    for metric in solar.METRICS:
        for stat in solar.STATS:
            assert e[(metric, stat, config.CURRENT)] == pytest.approx(e[(metric, stat, config.RESCINDED)])
            assert e[(metric, stat, config.PERMANENT)] == pytest.approx(e[(metric, stat, config.RESCINDED)])


def test_extremes_ordering():
    e = _extremes("America/Denver", 39.74, -104.99)
    for scen in config.SCENARIOS:
        assert e[("sunrise", "earliest", scen)] < e[("sunrise", "latest", scen)]
        assert e[("sunset", "earliest", scen)] < e[("sunset", "latest", scen)]


# --------------------------------------------------------------------- colours
def test_sequential_colors_are_distinct_and_get_darker():
    for n in (5, 7, 8, 14):
        cols = solar.sequential_colors(n)
        assert len(set(cols)) == n
        lum = [sum(int(c[i:i + 2], 16) * w for i, w in zip((1, 3, 5), (0.2126, 0.7152, 0.0722))) for c in cols]
        assert lum == sorted(lum, reverse=True)


def test_every_view_has_a_whole_number_of_bands():
    for key in config.SOLAR_SCALES:
        lo, hi, n = solar.scale_for(*key)
        assert (hi - lo) % config.SOLAR_BIN_MINUTES == 0 and n >= 2


def test_clock_formatting():
    assert solar.fmt_clock(20 * 60 + 5) == "8:05 PM"
    assert solar.fmt_clock(0) == "12:00 AM"
    assert solar.fmt_clock(12 * 60) == "12:00 PM"
    assert solar.fmt_label(7 * 60 + 30) == "7:30"
