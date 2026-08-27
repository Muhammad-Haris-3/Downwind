# Downwind

**Punjab publishes one air quality number per district. For 26 of 35 districts
that number comes from a single instrument.**

Downwind records what the province's air quality network says — and what it
fails to say — continuously, so that the question *"how wrong is a
single-station district number?"* can be answered with measurements rather than
argument.

> **Status: collecting. Nothing published.**
> [`PREREGISTRATION.md`](PREREGISTRATION.md) requires 60 continuous days and
> 150,000 station-hours before any figure appears, and those floors were fixed
> before the data existed.

---

## Why this exists

School closures, health advisories and smog emergencies in Punjab are triggered
by district air quality numbers. Coverage is genuinely broad — **55 stations
across 35 of 36 districts**. It is also thin: **74% of covered districts have
exactly one station**, asked to speak for millions of people across thousands of
square kilometres.

Where that assumption can be checked, it does not hold well. On the first day of
observation Lahore's ten stations disagreed by **78 AQI points** — three
different health categories at the same moment. Sheikhupura's three spread
**110 points**, from Moderate to Very Unhealthy.

That disagreement is not noise. Across two days the station ordering held at
**Spearman ρ = 0.82**, and disagreement scales with distance: Lahore station
pairs under 6 km apart differ by 18.5 AQI points on average, pairs over 20 km
apart by 36.7.

Four districts — Lahore, Faisalabad, Rawalpindi and Sheikhupura — have enough
stations to serve as a reference. Hold out all but one, measure how wrong the
survivor would have been, and that measured error becomes the honest uncertainty
on every single-station district in the province. Nobody currently publishes it.

**The premise this project started from was wrong, twice, and the feasibility
check is what caught it.** Both corrections are recorded in full in
[`FEASIBILITY.md`](FEASIBILITY.md), with the wrong numbers left visible beside
the right ones.

## What is being recorded

| Stream | What it holds |
|---|---|
| `readings` | Every station, every poll, verbatim. A district with no stations is recorded as such rather than skipped |
| `connectivity` | The network's own report of which stations are down — **kept even when it reports none**, because "none today" is evidence |
| `runs` | One record per poll, including every request that failed. Gaps in this stream are how the record stays honest about itself |

Polled four times an hour. Everything is stamped when observed, never when
scheduled.

**Two things make this necessary rather than optional.** The connectivity
endpoint is ephemeral — the department publishes what is down right now and
archives nothing. And deep history is key-gated, so nobody outside the
department can reconstruct the past. The only way a record exists is if someone
starts keeping one.

## What is deliberately not trusted

The published AQI is stored but not believed. One station reported **AQI 105 on
a PM2.5 of 6.7 µg/m³** — an index that requires roughly 37. The index is
recomputed downstream from raw pollutants. Readings carry no timestamp, and
station names are free-text join keys, so a rename would silently break a series.

## Running it

```bash
python -m pytest tests -q
python -m downwind.collect --data-dir data/raw
```

## Cost

**Zero.** No dependencies beyond the standard library, no database, no paid
quota. Collection runs on GitHub Actions, which is unlimited and free on public
repositories. Station coordinates come from an open source; the two feeds still
to be wired in (NASA FIRMS, OpenAQ) need free registration and no payment.
