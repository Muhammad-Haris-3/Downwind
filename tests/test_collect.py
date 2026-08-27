"""Tests for the collector.

The behaviour that matters most here is not "does it fetch" - it is "does it
still record when fetching fails". Every test below exists because losing a gap
would destroy the thing the project measures.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from downwind import collect
from downwind.store import Store

MOMENT = datetime(2026, 8, 27, 9, 30, tzinfo=timezone.utc)

STATION = {
    "station_name": "Multan Road",
    "aqi": 162,
    "pm25": "88.28",
    "pm10": "172.14",
    "co": "1.21",
    "so2": "85.59",
    "no2": "63.34",
    "o3": "14.37",
    "major_pollutant": "PM25",
}


@pytest.fixture
def frozen():
    return lambda: MOMENT


def fake_fetch(responses: dict[str, object]):
    """Return a _fetch stand-in; a value that is an Exception is raised."""

    def _fetch(path: str, **_: object) -> object:
        if path not in responses:
            raise collect.FetchError(f"no stub for {path}")
        value = responses[path]
        if isinstance(value, Exception):
            raise value
        return value

    return _fetch


def test_poll_records_stations(monkeypatch, frozen):
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Lahore"]},
                "district-stations/Lahore": {"data": [STATION]},
                "stations-with-connectivity-issues": {"has_issues": False, "count": 0},
            }
        ),
    )
    poll = collect.poll_once(delay=0, now=frozen)

    assert poll.failures == []
    assert len(poll.readings) == 1
    assert poll.readings[0]["raw"] == STATION
    assert poll.readings[0]["district"] == "Lahore"
    assert poll.readings[0]["observed_at_utc"] == MOMENT.isoformat()
    # PKT is UTC+5; the stamp must carry local time for smog-season day boundaries.
    assert poll.readings[0]["observed_at_pkt"].endswith("+05:00")


def test_empty_connectivity_response_is_still_recorded(monkeypatch, frozen):
    """An empty report is evidence. Discarding it would fabricate uptime."""
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Lahore"]},
                "district-stations/Lahore": {"data": [STATION]},
                "stations-with-connectivity-issues": {
                    "has_issues": False,
                    "stations": [],
                    "count": 0,
                },
            }
        ),
    )
    poll = collect.poll_once(delay=0, now=frozen)

    assert len(poll.connectivity) == 1
    assert poll.connectivity[0]["raw"]["count"] == 0


def test_failed_district_does_not_abort_the_sweep(monkeypatch, frozen):
    """One dead district must not cost us the other thirty-five."""
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Lahore", "Multan", "Murree"]},
                "district-stations/Lahore": {"data": [STATION]},
                "district-stations/Multan": collect.FetchError("boom"),
                "district-stations/Murree": {"data": [STATION]},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    poll = collect.poll_once(delay=0, now=frozen)

    assert len(poll.readings) == 2
    assert len(poll.failures) == 1
    assert poll.failures[0]["target"] == "district-stations/Multan"


def test_district_with_zero_stations_is_recorded_not_skipped(monkeypatch, frozen):
    """Dera Ghazi Khan reports no stations. That is a fact, not an absence."""
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Dera Ghazi Khan"]},
                "district-stations/Dera%20Ghazi%20Khan": {"data": []},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    poll = collect.poll_once(delay=0, now=frozen)

    assert len(poll.readings) == 1
    assert poll.readings[0]["empty_district"] is True


def test_district_names_are_url_quoted(monkeypatch, frozen):
    seen: list[str] = []

    def _fetch(path: str, **_: object) -> object:
        seen.append(path)
        if path == "districts":
            return {"districts": ["Rahim Yar Khan"]}
        return {"data": [STATION], "count": 0}

    monkeypatch.setattr(collect, "_fetch", _fetch)
    collect.poll_once(delay=0, now=frozen)

    assert "district-stations/Rahim%20Yar%20Khan" in seen


def test_district_list_failure_returns_empty_poll_not_crash(monkeypatch, frozen):
    monkeypatch.setattr(
        collect, "_fetch", fake_fetch({"districts": collect.FetchError("down")})
    )
    poll = collect.poll_once(delay=0, now=frozen)

    assert poll.readings == []
    assert poll.failures[0]["target"] == "districts"


def test_run_writes_partitions_and_marks_incompleteness(monkeypatch, tmp_path):
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Lahore", "Multan"]},
                "district-stations/Lahore": {"data": [STATION]},
                "district-stations/Multan": collect.FetchError("boom"),
                "stations-with-connectivity-issues": {"count": 2},
            }
        ),
    )
    store = Store(tmp_path)
    record = collect.run(store, delay=0)

    assert record["station_readings"] == 1
    assert record["stations_reporting_issues"] == 2
    assert record["complete"] is False
    assert record["districts_polled"] == 2

    day = datetime.fromisoformat(record["started_at_utc"])
    assert store.count("readings", day) == 1
    assert store.count("connectivity", day) == 1
    assert store.count("runs", day) == 1


def test_fetch_retries_then_raises(monkeypatch):
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise OSError("network down")

    monkeypatch.setattr(collect.urllib.request, "urlopen", boom)
    monkeypatch.setattr(collect.time, "sleep", lambda _s: None)

    with pytest.raises(collect.FetchError):
        collect._fetch("districts")

    assert calls["n"] == collect.RETRIES + 1


def test_headers_carry_origin():
    """Without Origin the API returns 403 INVALID_ORIGIN. Regression guard."""
    assert collect.HEADERS["Origin"] == "https://aqi.punjab.gov.pk"


def test_run_many_polls_repeatedly_and_paces_itself(monkeypatch, tmp_path):
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Lahore"]},
                "district-stations/Lahore": {"data": [STATION]},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    slept: list[float] = []
    store = Store(tmp_path)
    records = collect.run_many(
        store, polls=3, interval=900, delay=0, sleep=slept.append
    )

    assert len(records) == 3
    # Paced between polls, but never after the last one.
    assert len(slept) == 2
    assert all(0 < s <= 900 for s in slept)
    assert len({r["poll_id"] for r in records}) == 3


def test_cached_district_list_rescues_a_poll(monkeypatch, tmp_path, frozen):
    """One bad second on /api/districts must not cost 55 stations.

    This is the failure the first CI collection actually hit.
    """
    cache = tmp_path / "districts.json"
    collect.save_cached_districts(cache, ["Lahore", "Murree"])
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": collect.FetchError("urlopen error timed out"),
                "district-stations/Lahore": {"data": [STATION]},
                "district-stations/Murree": {"data": [STATION]},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    poll = collect.poll_once(delay=0, now=frozen, district_cache=cache)

    assert len(poll.readings) == 2
    assert poll.district_source == "cache"
    # The failure is still recorded. Recovering from it must not hide it.
    assert poll.failures[0]["target"] == "districts"
    assert poll.failures[0]["fallback"] == "cache"


def test_successful_fetch_refreshes_the_cache(monkeypatch, tmp_path, frozen):
    cache = tmp_path / "districts.json"
    collect.save_cached_districts(cache, ["Stale"])
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Lahore", "Kot Addu"]},
                "district-stations/Lahore": {"data": [STATION]},
                "district-stations/Kot%20Addu": {"data": [STATION]},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    poll = collect.poll_once(delay=0, now=frozen, district_cache=cache)

    assert poll.district_source == "live"
    assert collect.load_cached_districts(cache) == ["Lahore", "Kot Addu"]


def test_no_cache_and_no_network_yields_an_empty_poll(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(
        collect, "_fetch", fake_fetch({"districts": collect.FetchError("down")})
    )
    poll = collect.poll_once(
        delay=0, now=frozen, district_cache=tmp_path / "absent.json"
    )

    assert poll.readings == []
    assert poll.district_source == "unavailable"


def test_corrupt_cache_is_treated_as_absent(tmp_path):
    bad = tmp_path / "districts.json"
    bad.write_text("{not json", encoding="utf-8")
    assert collect.load_cached_districts(bad) == []


def test_run_record_names_the_district_source(monkeypatch, tmp_path):
    cache = tmp_path / "districts.json"
    collect.save_cached_districts(cache, ["Lahore"])
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": collect.FetchError("timed out"),
                "district-stations/Lahore": {"data": [STATION]},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    record = collect.run(Store(tmp_path), delay=0, district_cache=cache)

    assert record["district_source"] == "cache"
    assert record["station_readings"] == 1
    assert record["complete"] is False


def test_poll_stops_at_its_budget_and_names_what_it_missed(monkeypatch, tmp_path, frozen):
    """A slow API must cost a bounded amount of time, not half an hour.

    The CI run that prompted this spent eleven minutes inside one poll.
    """
    cache = tmp_path / "districts.json"
    districts = ["A", "B", "C", "D", "E"]
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": districts},
                **{f"district-stations/{d}": {"data": [STATION]} for d in districts},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    # Clock advances 100s per reading; the 250s budget allows three districts.
    ticks = iter([0, 0, 100, 200, 300, 400, 500, 600])
    poll = collect.poll_once(
        delay=0,
        now=frozen,
        district_cache=cache,
        budget_seconds=250,
        clock=lambda: next(ticks),
    )

    assert poll.budget_exhausted is True
    assert poll.districts_unreached == ["D", "E"]
    assert len(poll.readings) == 3
    assert poll.failures[-1]["target"] == "poll"
    assert poll.failures[-1]["unreached"] == 2


def test_a_poll_within_budget_reports_nothing_unreached(monkeypatch, tmp_path, frozen):
    cache = tmp_path / "districts.json"
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": ["Lahore"]},
                "district-stations/Lahore": {"data": [STATION]},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    poll = collect.poll_once(delay=0, now=frozen, district_cache=cache)

    assert poll.budget_exhausted is False
    assert poll.districts_unreached == []


def test_run_record_separates_listed_from_polled(monkeypatch, tmp_path):
    cache = tmp_path / "districts.json"
    districts = ["A", "B", "C"]
    monkeypatch.setattr(
        collect,
        "_fetch",
        fake_fetch(
            {
                "districts": {"districts": districts},
                **{f"district-stations/{d}": {"data": [STATION]} for d in districts},
                "stations-with-connectivity-issues": {"count": 0},
            }
        ),
    )
    monkeypatch.setattr(collect.time, "monotonic", lambda: 10**9)
    record = collect.run(Store(tmp_path), delay=0, district_cache=cache, budget_seconds=0)

    assert record["districts_listed"] == 3
    assert record["districts_polled"] == 0
    assert record["budget_exhausted"] is True
    assert record["complete"] is False
