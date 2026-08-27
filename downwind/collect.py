"""Poll the Punjab AQI network and record what it says, including its silences.

Three things are recorded on every run:

* ``readings``     - one record per station per poll, verbatim from the API.
* ``connectivity`` - the network's own report of which stations are down, kept
                     even when it reports none, because "none today" is evidence.
* ``runs``         - one record per poll describing the poll itself, including
                     every request that failed.

Nothing is transformed here. The published AQI is stored as given and is *not*
trusted: at least one station has reported an index inconsistent with its own
pollutant readings, so the index is recomputed downstream from raw pollutants.
See FEASIBILITY.md.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from . import SCHEMA_VERSION
from .store import Store

BASE_URL = "https://aqi.punjab.gov.pk/api"

# The API rejects requests without a browser Origin (403 INVALID_ORIGIN).
HEADERS = {
    "Origin": "https://aqi.punjab.gov.pk",
    "Referer": "https://aqi.punjab.gov.pk/",
    "Accept": "application/json",
    "User-Agent": "Downwind/0.1 (research collector; contact via repository)",
}

PKT = timezone(timedelta(hours=5))

REQUEST_TIMEOUT = 30.0
RETRIES = 2
RETRY_BACKOFF = 3.0
POLITE_DELAY = 0.25

# The district list changes on the order of months; a cached copy keeps a
# momentary failure on one endpoint from costing a whole poll.
DISTRICT_CACHE = Path("data/districts.json")


class FetchError(Exception):
    """A request that did not return usable JSON after all retries."""


@dataclass
class Poll:
    """One complete sweep of the network."""

    poll_id: str
    started_at: datetime
    readings: list[dict[str, Any]] = field(default_factory=list)
    connectivity: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    districts_seen: list[str] = field(default_factory=list)
    district_source: str = "live"


def _fetch(path: str, *, timeout: float = REQUEST_TIMEOUT) -> Any:
    """GET ``path`` under the API base and return parsed JSON.

    Retries transient failures. Raises FetchError once retries are exhausted so
    the caller can record the failure rather than lose the whole poll.
    """
    url = f"{BASE_URL}/{path}"
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - every failure mode is recorded
            last = exc
            if attempt < RETRIES:
                time.sleep(RETRY_BACKOFF * (attempt + 1))
    raise FetchError(f"{url}: {type(last).__name__}: {last}") from last


def fetch_districts() -> list[str]:
    """The network's own district list.

    This must never be replaced by a district list from a boundary file. The two
    disagree: the API includes Kot Addu, Murree, Wazirabad and DG Khan, and omits
    Bahawalnagar, Layyah, Lodhran and Toba Tek Singh. Using a boundary file
    silently loses four districts. See the FEASIBILITY.md addendum.
    """
    payload = _fetch("districts")
    districts = payload.get("districts") or []
    if not districts:
        raise FetchError("districts endpoint returned an empty list")
    return list(districts)


def load_cached_districts(path: Path) -> list[str]:
    """The last district list that was successfully fetched, if any."""
    try:
        return list(json.loads(path.read_text(encoding="utf-8"))["districts"])
    except Exception:  # noqa: BLE001 - a missing or corrupt cache is just absent
        return []


def save_cached_districts(path: Path, districts: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"districts": districts}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_districts(cache: Path) -> tuple[list[str], str, str | None]:
    """Get the district list, falling back to the last known one.

    The first CI collection lost an entire poll because `/api/districts` timed
    out for one moment and the sweep treated that as fatal. The district list
    changes on the order of months, so one bad second on one endpoint must not
    cost a poll of fifty-five stations. Returns the list, its source, and the
    error if the live fetch failed.
    """
    try:
        districts = fetch_districts()
    except FetchError as exc:
        cached = load_cached_districts(cache)
        if cached:
            return cached, "cache", str(exc)
        return [], "unavailable", str(exc)
    save_cached_districts(cache, districts)
    return districts, "live", None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> dict[str, str]:
    return {
        "observed_at_utc": moment.isoformat(),
        "observed_at_pkt": moment.astimezone(PKT).isoformat(),
    }


def poll_once(
    *,
    delay: float = POLITE_DELAY,
    now: Callable[[], datetime] = _utcnow,
    district_cache: Path = DISTRICT_CACHE,
) -> Poll:
    """Sweep every district once and return everything observed.

    A poll is never abandoned because part of it failed. A district that cannot
    be fetched is recorded as a failure and the sweep continues, because a gap
    in the record is exactly the thing this project exists to measure.
    """
    started = now()
    poll = Poll(poll_id=uuid.uuid4().hex, started_at=started)

    districts, source, error = resolve_districts(district_cache)
    poll.district_source = source
    if error:
        poll.failures.append({"target": "districts", "error": error, "fallback": source})
    if not districts:
        return poll
    poll.districts_seen = districts

    for district in districts:
        moment = now()
        try:
            payload = _fetch(f"district-stations/{urllib.parse.quote(district)}")
        except FetchError as exc:
            poll.failures.append(
                {"target": f"district-stations/{district}", "error": str(exc)}
            )
            time.sleep(delay)
            continue

        stations = payload.get("data") or []
        if not stations:
            # A district with no stations is a fact worth keeping, not a blank.
            poll.readings.append(
                {
                    "schema": SCHEMA_VERSION,
                    "poll_id": poll.poll_id,
                    "district": district,
                    "empty_district": True,
                    **_stamp(moment),
                }
            )
        for station in stations:
            poll.readings.append(
                {
                    "schema": SCHEMA_VERSION,
                    "poll_id": poll.poll_id,
                    "district": district,
                    "empty_district": False,
                    **_stamp(moment),
                    "raw": station,
                }
            )
        time.sleep(delay)

    moment = now()
    try:
        payload = _fetch("stations-with-connectivity-issues")
        poll.connectivity.append(
            {
                "schema": SCHEMA_VERSION,
                "poll_id": poll.poll_id,
                **_stamp(moment),
                "raw": payload,
            }
        )
    except FetchError as exc:
        poll.failures.append(
            {"target": "stations-with-connectivity-issues", "error": str(exc)}
        )

    return poll


def run(
    store: Store,
    *,
    delay: float = POLITE_DELAY,
    district_cache: Path = DISTRICT_CACHE,
) -> dict[str, Any]:
    """Poll once and persist everything. Returns the run record."""
    poll = poll_once(delay=delay, district_cache=district_cache)
    finished = _utcnow()

    n_readings = store.append("readings", poll.started_at, poll.readings)
    n_connectivity = store.append("connectivity", poll.started_at, poll.connectivity)

    stations = sum(1 for r in poll.readings if not r.get("empty_district"))
    issues = 0
    for record in poll.connectivity:
        raw = record.get("raw") or {}
        issues += int(raw.get("count") or 0)

    record = {
        "schema": SCHEMA_VERSION,
        "poll_id": poll.poll_id,
        "started_at_utc": poll.started_at.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "duration_seconds": round((finished - poll.started_at).total_seconds(), 2),
        "districts_polled": len(poll.districts_seen),
        "district_source": poll.district_source,
        "districts": poll.districts_seen,
        "station_readings": stations,
        "records_written": {"readings": n_readings, "connectivity": n_connectivity},
        "stations_reporting_issues": issues,
        "failures": poll.failures,
        "complete": not poll.failures,
    }
    store.append("runs", poll.started_at, [record])
    return record


def run_many(
    store: Store,
    *,
    polls: int,
    interval: float,
    delay: float = POLITE_DELAY,
    district_cache: Path = DISTRICT_CACHE,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Poll ``polls`` times, ``interval`` seconds apart, measured from each start.

    Several polls per CI job rather than one job per poll: a scheduled runner
    costs a minute of setup for a fifty-second poll, and hourly jobs leave a
    gap of at most an hour if a runner dies. Gaps are visible in the runs
    stream either way, which is what keeps the record honest about itself.
    """
    records: list[dict[str, Any]] = []
    for index in range(polls):
        started = time.monotonic()
        records.append(run(store, delay=delay, district_cache=district_cache))
        if index < polls - 1:
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                sleep(remaining)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll the Punjab AQI network.")
    parser.add_argument("--data-dir", default=Path("data/raw"), type=Path)
    parser.add_argument("--delay", default=POLITE_DELAY, type=float)
    parser.add_argument("--polls", default=1, type=int, help="polls per invocation")
    parser.add_argument(
        "--interval", default=900.0, type=float, help="seconds between poll starts"
    )
    args = parser.parse_args(argv)

    records = run_many(
        Store(args.data_dir),
        polls=args.polls,
        interval=args.interval,
        delay=args.delay,
    )
    print(json.dumps(records, indent=2, default=str))
    # A partial poll is still a successful collection: the gaps are the data.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
