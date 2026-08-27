# Downwind — pre-registration v1.0

**Committed 27 August 2026, before the 2026–27 smog season and before any
sustained data exists.** Two days of pilot data had been seen when this was
written; that pilot is described in [`FEASIBILITY.md`](FEASIBILITY.md) and is
explicitly *not* part of any result reported under this document.

Everything below is fixed. Changes require a numbered amendment stating what
changed, why, and what had already been seen — kept in git history alongside the
original.

---

## 1. The question

Punjab publishes one air quality number per district. For 22 of 31 covered
districts that number comes from a single instrument.

**How wrong is a single-station district number, and does the error cross the
boundaries that health advice is built on?**

---

## 2. Primary test — hold-one-out

In districts with ≥3 stations, treat the mean of all stations as the district
reference. Then, for each station in turn, compute the error that station would
have produced had it been the district's only monitor.

**Primary outcome:** the share of station-hours where a single-station estimate
falls in a **different US EPA AQI health category** than the district reference.

**Reported as:** a distribution, by district, by hour of day, and by season phase
— never as a single headline number.

---

## 3. Thresholds, fixed now

| | Threshold |
|---|---|
| Minimum collection before *any* figure is published | **60 continuous days** and **≥150,000 station-hours** |
| Minimum stations in a district to serve as reference | **3** |
| Minimum valid hours for a station-day to count | **18 of 24** |
| Sustained rank correlation below which the project is killed | **ρ < 0.4 over any 30-day window** |
| Category-disagreement rate below which the finding is "no effect" | **< 10% of station-hours** |

The 10% figure is set now, with no idea what the answer will be. The pilot's
single instant showed three categories inside Lahore at once; if that turns out
to be unrepresentative and the real rate is 4%, that is the finding and it gets
published as such.

---

## 4. Forecasts committed before outcomes

Every day, for every district, Downwind publishes a next-day AQI estimate
**before the day begins**, written to an append-only store that the writing role
cannot `UPDATE` or `DELETE`.

**Benchmarks, chosen now, not after seeing results:**

1. **Persistence** — tomorrow equals today. The baseline that is embarrassing to lose to.
2. **Open-Meteo / CAMS** — an independent free model estimate for the same point.
3. **District's own single station**, where one exists.

A forecast enters a published accuracy figure only after its outcome has settled
and the station reported ≥18 valid hours. **No provisional accuracy will be
shown, at any point, for any reason.**

---

## 5. The downtime register

`stations-with-connectivity-issues` is polled every 15 minutes and every response
is stored, including empty ones. An empty response is evidence and is kept as
evidence.

**Secondary outcome:** total station-hours lost to downtime, by station and by
district, and the share of those lost hours that fall on days the surrounding
district was above AQI 150.

This measures the thing the pitch was originally about: **bad air that happened
and was recorded nowhere.**

---

## 6. What gets published regardless of result

- The hold-one-out error distribution, including if it is small.
- The downtime register, including if downtime turns out to be negligible.
- Every forecast, including the ones that lost to persistence.
- The Model Town AQI/PM2.5 inconsistency and any others found, whether or not
  they are ever fixed.
- This document, unedited, next to whatever the results turn out to be.

## 7. What will not be claimed

- **No health outcomes.** Downwind does not estimate illness, hospital
  admissions, or deaths. It has no data to support that and will not imply it.
- **No source attribution.** Fire counts near a district are a covariate, not a
  finding about who caused what.
- **No claim that the department is wrong to run the network as it does.** The
  finding, if there is one, is about what a single number can carry — not about
  intent, competence, or bad faith.
- **No estimate for the 5 uncovered districts** unless the hold-out test first
  establishes the method works where it can be checked.
