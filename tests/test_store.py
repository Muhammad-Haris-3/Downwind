"""Tests for append-only storage.

The single property worth guarding: a second write must never destroy the first.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from downwind.store import Store

DAY = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def test_append_then_append_keeps_both(tmp_path):
    store = Store(tmp_path)
    store.append("readings", DAY, [{"n": 1}])
    store.append("readings", DAY, [{"n": 2}])

    assert [r["n"] for r in store.read("readings", DAY)] == [1, 2]


def test_partitions_split_by_utc_day(tmp_path):
    store = Store(tmp_path)
    store.append("readings", DAY, [{"n": 1}])
    store.append("readings", DAY + timedelta(days=1), [{"n": 2}])

    assert store.count("readings", DAY) == 1
    assert store.count("readings", DAY + timedelta(days=1)) == 1


def test_partition_name_is_the_utc_date(tmp_path):
    store = Store(tmp_path)
    assert store.partition("readings", DAY).name == "2026-10-15.ndjson"


def test_reading_a_missing_partition_is_empty_not_an_error(tmp_path):
    assert list(Store(tmp_path).read("readings", DAY)) == []


def test_unicode_survives_a_round_trip(tmp_path):
    """Station names may carry non-ASCII; mangling them breaks the join key."""
    store = Store(tmp_path)
    store.append("readings", DAY, [{"station": "Multan Road — Chung"}])

    assert list(store.read("readings", DAY))[0]["station"] == "Multan Road — Chung"


def test_records_are_one_line_each(tmp_path):
    store = Store(tmp_path)
    store.append("readings", DAY, [{"a": 1}, {"b": 2}, {"c": 3}])

    text = store.partition("readings", DAY).read_text(encoding="utf-8")
    assert len([line for line in text.splitlines() if line.strip()]) == 3


def test_append_returns_count_written(tmp_path):
    assert Store(tmp_path).append("readings", DAY, [{"a": 1}, {"b": 2}]) == 2
