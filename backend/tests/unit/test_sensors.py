"""Chart data for wind direction, gusts, cloud base, sky condition, present weather and lightning."""

from __future__ import annotations

from datetime import UTC, datetime

from simola.kpi import sensors as s

T0 = int(datetime(2026, 11, 1, tzinfo=UTC).timestamp() * 1000)
M = s.MINUTE_MS


def minutes(n: int, skip: tuple[int, ...] = ()) -> list[int]:
    return [T0 + i * M for i in range(n) if i not in skip]


# ---------------------------------------------------------------------------- dots and cloud base


def test_cloud_base_zero_means_no_cloud() -> None:
    out = s.dot_series(minutes(5), [0.0, 12.0, None, 0.0, 30.0], 5, zero_is_none=True)
    assert out == {"t": [T0 + M, T0 + 4 * M], "v": [12.0, 30.0], "downsampled": False}
    stats = s.nonzero_stats({"last": None, "count": 4}, [0.0, 12.0, None, 0.0, 30.0])
    assert (stats["count"], stats["zero_minutes"], stats["min"], stats["max"], stats["mean"]) == (
        2,
        2,
        12.0,
        30.0,
        21.0,
    )


def test_long_windows_keep_each_buckets_lowest_and_highest() -> None:
    n = 31 * 1440
    values = [float(100 + (i * 37) % 250) for i in range(n)]
    values[12_345] = 1.0  # the lowest cloud base of the month must survive
    out = s.dot_series(minutes(n), values, n)
    assert out["downsampled"] and len(out["t"]) <= 2 * s.MAX_DOTS
    assert min(out["v"]) == 1.0 and max(out["v"]) == max(values)
    assert out["t"] == sorted(out["t"])


# ---------------------------------------------------------------------------- gusts


def test_gust_events_break_at_calm_missing_and_gaps() -> None:
    ms = minutes(12, skip=(8,))  # minute 8 has no record
    gs = [0, 15, 22, 22, 0, None, 18, 0, 25, 0, 12]
    gd = [0, 200, 240, 250, 0, None, 90, 0, 300, 0, 10]
    out = s.gust_events(ms, gs, gd)
    assert out["event_count"] == 4 and out["minutes"] == 6
    first = out["events"][0]
    assert (first["minutes"], first["max_kt"], first["direction_deg"]) == (
        3,
        22.0,
        240,
    )  # first of equal maxima
    assert out["strongest"]["max_kt"] == 25.0 and out["strongest"]["direction_deg"] == 300
    assert out["strongest"]["start"] == datetime(2026, 11, 1, 0, 9, tzinfo=UTC)


def test_a_gap_inside_gusts_splits_the_event() -> None:
    out = s.gust_events(minutes(4, skip=(2,)), [10, 11, 12], [1, 2, 3])
    assert [e["minutes"] for e in out["events"]] == [2, 1]


# ---------------------------------------------------------------------------- sky condition


def test_parse_sky() -> None:
    assert s.parse_sky("FEW020 BKN060CB OVC220")["layers"] == [
        ("FEW", 2000, None),
        ("BKN", 6000, "CB"),
        ("OVC", 22000, None),
    ]
    assert s.parse_sky("VV005") == {"layers": [], "vv": 500, "obscured": True, "clear": False}
    assert s.parse_sky("NCD")["clear"] is True
    assert (s.band(6499), s.band(6500), s.band(19999), s.band(20000)) == ("low", "middle", "middle", "high")


def test_sky_summary_counts_the_densest_layer_per_band_and_the_lowest_ceiling() -> None:
    ms = minutes(5)
    vals = ["FEW020 SCT030 BKN150", "NCD", "VV004", "OVC010 FEW250", None]
    out = s.sky_summary(ms, vals, 5)
    assert out["band_minutes"]["low"] == {"FEW": 0, "SCT": 1, "BKN": 0, "OVC": 1}
    assert out["band_minutes"]["middle"]["BKN"] == 1 and out["band_minutes"]["high"]["FEW"] == 1
    assert (out["clear_minutes"], out["obscured_minutes"], out["reported_minutes"]) == (1, 1, 4)
    assert out["lowest_ceiling"]["cover"] == "VV" and out["lowest_ceiling"]["height_ft"] == 400
    assert len(out["timeline"]) == 4 and out["timeline"][1]["clear"] is True


# ---------------------------------------------------------------------------- present weather


def test_parse_weather_codes() -> None:
    assert s.parse_weather("-TSRA") == {"thunderstorm": 1, "rain": 1}
    assert s.parse_weather("VCTS DZ") == {"thunderstorm": 1, "drizzle": 2}
    assert s.parse_weather("+RA") == {"rain": 3}
    assert s.parse_weather("TS HZ") == {"thunderstorm": 2, "haze": 2}
    assert s.parse_weather("BR") == {"mist_fog": 2} and s.parse_weather("FG") == {"mist_fog": 2}
    assert s.parse_weather("VCTS D") == {"thunderstorm": 1, "other": 2}  # cut off by the old reader
    assert s.parse_weather("") == {}


def test_weather_rows_and_segments() -> None:
    ms = minutes(6)
    out = s.weather_summary(ms, ["", "-RA", "RA", "", "BR", None], 6)
    rows = {r["key"]: r for r in out["rows"]}
    assert rows["rain"]["minutes"] == 2 and rows["rain"]["segments"] == [[T0 + M, T0 + 3 * M, 2, "-RA"]]
    assert rows["mist_fog"]["segments"] == [[T0 + 4 * M, T0 + 5 * M, 2, "BR"]]
    assert (out["weather_minutes"], out["reported_minutes"]) == (3, 5)


# ---------------------------------------------------------------------------- lightning


def test_parse_lightning() -> None:
    assert s.parse_lightning("TS in Vicinity - LTG DSNT NE AND E") == ("vicinity", ("NE", "E"))
    assert s.parse_lightning("TS at Airport - LTG DSNT ALQDS") == ("airport", ("ALQDS",))
    assert s.parse_lightning("LTG DSNT SW AND W") == ("distant", ("SW", "W"))
    assert s.parse_lightning("TS in Vicinity - LTG DSNT NE AND") == (
        "vicinity",
        ("NE",),
    )  # cut off by the old reader
    assert s.parse_lightning("TS at Airport") == ("airport", ())
    assert s.parse_lightning("") == (None, ())


def test_lightning_episodes_and_directions() -> None:
    ms = minutes(40)
    vals: list[str | None] = [""] * 40
    vals[2] = vals[3] = "LTG DSNT E"
    vals[10] = "TS in Vicinity - LTG DSNT E AND W"  # 7 quiet minutes: same episode
    vals[30] = "TS at Airport"  # 20 quiet minutes: a new episode
    out = s.lightning_summary(ms, vals, 40)
    assert out["episodes"] == 2
    assert {r["key"]: r["minutes"] for r in out["rows"]} == {"airport": 1, "vicinity": 1, "distant": 2}
    assert out["directions"]["E"] == 3 and out["directions"]["W"] == 1
    assert out["first"] == datetime(2026, 11, 1, 0, 2, tzinfo=UTC)
