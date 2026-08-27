# Downwind — feasibility check

**Checked 27 August 2026. Every number below was measured, not quoted.**
Raw pilot data in [`data/pilot/`](data/pilot/).

---

## Verdict

**Build it — but not the project that was pitched.** The premise the pitch rested
on is wrong, and the feasibility check is what caught it. A better question
survived, and it is checkable.

---

## The premise that was wrong

The pitch claimed Punjab has roughly 30 monitoring stations and that *most
districts have no monitor at all*, so bad air days in unmonitored districts go
unrecorded.

That was based on a January 2025 newspaper report. It is out of date.

**Measured today by enumerating every district in the province:**

| | |
|---|---|
| Stations returning live readings | **51** |
| Punjab districts in the boundary file | 36 |
| Districts with at least one station | **31** |
| Districts listed but with zero stations | 1 (Dera Ghazi Khan) |
| Districts not in the system at all (HTTP 404) | 4 (Bahawalnagar, Layyah, Lodhran, Toba Tek Singh) |

Coverage is **broad**. The monitor-desert story does not hold for Punjab, and any
version of this project that leads with it would be starting from a false claim.

---

## The question that survived

Coverage is broad. It is also **thin**.

**22 of the 31 covered districts — 71% — have exactly one station.** One
instrument is asked to speak for a district of several million people across
thousands of square kilometres, and the number it produces is what triggers
school closures and health advisories.

So the question is not *"where is there no monitor?"* It is:

> **When a district is represented by a single number, how wrong is that number —
> and is it wrong by enough to change what people are told to do?**

This is answerable, because a few districts have several stations. Lahore has
ten. Those districts are a natural laboratory: hold out nine of Lahore's ten
stations, and you can measure exactly how wrong the survivor would have been.
That measured error is the honest uncertainty on every one-station district in
the province — a figure nobody currently publishes.

The Downfall structure holds, just relocated. The number exists. It does not mean
what it is taken to mean.

---

## Pilot finding (two observations, 51 stations)

**At one instant, Lahore's ten stations disagreed by 78 AQI points** — 84 at
Wagha Border to 162 on Multan Road. That spans **three different health
categories simultaneously**: Moderate, Unhealthy for Sensitive Groups, and
Unhealthy. The worst single station sat 41.6 points from the district mean.

**Sheikhupura, with three stations, spread 110 points** — 93 to 203. One of its
stations said Moderate while another said Very Unhealthy.

**Yesterday, Lahore spread 106 points** — 64 to 170.

The critical test was whether this is spatial structure or instantaneous noise.

> **Spearman rank correlation between today's and yesterday's Lahore station
> ordering: ρ = 0.82 (n = 7).**

Stations hold their rank. Multan Road was highest on both days (162, 161); DHA
Phase 6 near the bottom on both (96, 64). **The disagreement is a persistent
property of place, not measurement jitter.** That is what makes the project
viable — a stable signal can be modelled; noise cannot.

Two days is a pilot, not a result. It is enough to justify building, and nowhere
near enough to publish.

---

## Feeds, verified individually

| Feed | Status | Notes |
|---|---|---|
| `aqi.punjab.gov.pk/api/district-stations/{district}` | **Works** | AQI + PM2.5, PM10, CO, SO₂, NO₂, O₃ per station. Requires an `Origin` header; returns 403 without it |
| `.../api/stations-with-connectivity-issues` | **Works** | Returns which stations are down, right now. Currently `count: 0` |
| `.../api/station-yesterday-aqi/{station}` | **Works** | One day back, per station |
| `.../api/historical/24hours` | **Blocked** | `MISSING_API_KEY` |
| `.../api/historical-aqi-data` | **Blocked** | CSRF-gated (419) |
| `robots.txt` | **Permits all** | `Disallow:` empty. No terms-of-use page exists (checked 6 paths, all 404) |
| Rate limiting | **None observed** | 8 rapid consecutive calls, all 200 |
| District boundaries | **Works** | Served by the dashboard itself: 148 features, all Pakistan, district + province fields |
| Open-Meteo Air Quality | **Works, keyless** | PM2.5, PM10, dust, aerosol optical depth, CO. 5 days back + 5 forward |
| Open-Meteo ERA5 archive | **Works, keyless** | Includes **boundary layer height** — the variable that governs whether pollution accumulates |
| NASA FIRMS (crop fires) | **Free key required** | 401 without `MAP_KEY`. Registration is free |
| OpenAQ v3 | **Free key required** | 401 without key. v1/v2 retired (410) |

**Total cost: zero.** Two free registrations, no payment, no quota purchase.

---

## The two things this makes possible that do not currently exist

**1. A downtime record.** The government publishes which stations are down *right
now* and keeps no archive of it. That endpoint is ephemeral — poll it every
fifteen minutes for a season and you hold the only history of it that exists.
When a station is dark during a smog episode, that district's bad day is recorded
nowhere. This is already visible: **5 of 51 stations returned no value for
yesterday.**

**2. A history at all.** Deep history is key-gated. Nobody outside the department
can reconstruct the past. **The only way to have a record is to start keeping one
now** — which is precisely why the project has to run through a season before it
can say anything, and why waiting is the design rather than a delay.

---

## Data quality problems found on day one

- **Model Town, Lahore reported AQI 105 on a PM2.5 of 6.7 µg/m³.** Those are not
  consistent; an AQI of 105 on PM2.5 requires roughly 37 µg/m³. Either another
  pollutant is driving the index there or the reading is bad. Any pipeline must
  recompute AQI from raw pollutants rather than trusting the published index.
- **Readings carry no timestamp.** Observation time must be stamped at poll,
  which means poll cadence *is* the temporal resolution.
- **Station names are the only join key**, and they are free text
  (`"Model Town, Lahore"`). A rename silently breaks the series.

---

## Not yet verified

- **District population figures** for exposure weighting. Candidate sources: PBS
  2023 census, HDX. Unchecked — do not assume.
- **Station coordinates.** The district endpoint returns names, not locations. A
  hold-out analysis needs positions; if they are not obtainable, the primary test
  weakens to a district-level one.
- **Whether coverage is stable.** 51 stations today. The count moved a lot since
  January 2025 and may move again mid-season, which would break a fixed panel.

---

## Kill conditions

Fixed now, before any results exist. See [`PREREGISTRATION.md`](PREREGISTRATION.md).

1. **Station coordinates unobtainable within two weeks** → the hold-out test
   cannot be run properly. Downgrade scope or stop.
2. **Rank correlation collapses over a full month** (ρ < 0.4 sustained) → the
   spread is noise, not place. The project has no finding. Publish that and stop.
3. **Hold-one-out error never crosses a health-category boundary** in a month of
   data → single stations are good enough. That is a real, useful, negative
   answer. Publish it and stop.
4. **The API closes or starts requiring credentials** → stop, publish what was
   collected.

Outcome 2 and 3 are not failures. Triage killed itself and is the better for it.

---

# Addendum — 27 August 2026: coordinates resolved, counts corrected

## Kill condition #1 is cleared

**Station coordinates are obtainable.** The Punjab API does not expose them
(`/api/stations` returns `MISSING_API_KEY`), but the aqicn.org Punjab network
page embeds `"g":[lat,lon]` per station. **42 of 55 official stations matched by
name.**

What matters is coverage in the districts the primary test depends on:

| district | stations | located | usable as hold-out reference |
|---|---|---|---|
| Lahore | 10 | 9 | **yes** |
| Faisalabad | 3 | 3 | **yes** |
| Rawalpindi | 3 | 3 | **yes** |
| Sheikhupura | 3 | 3 | **yes** |
| Bahawalpur, Gujranwala, Sargodha | 2 | 2 | pairs only |
| Chakwal, Multan | 2 | 1 | no |

**Four districts support the hold-out test.** The 13 unmatched stations are
almost all in single-station districts, where they are the subject of the test
rather than the reference. Most are manually geocodable (`DC Office Kasur`,
`Talagang`, `Murree`). The one costly miss is **Model Town, Lahore** — the same
station that produced the impossible AQI 105 on 6.7 µg/m³.

## The signal the whole project rests on

Across Lahore's 9 located stations — 36 pairs, separated by 3.1 to 39.5 km:

| pair separation | n | mean AQI difference |
|---|---|---|
| **under 6 km** | 2 | **18.5** |
| **over 20 km** | 14 | **36.7** |

**Disagreement grows with distance.** That is the thing a model can learn, and it
is what converts "one station is unrepresentative" from a complaint into a
measurable function. Two stations 3.1 km apart differ by 13 AQI points; two 39.5
km apart differ by 38.

## Corrections to the counts above

Querying `/api/districts` — found after the first enumeration — returns the
system's authoritative district list, which is **not** the boundary file's list.
It includes Kot Addu, Murree, Wazirabad and DG Khan, and omits Bahawalnagar,
Layyah, Lodhran and Toba Tek Singh entirely.

Re-run against the authoritative list:

| | first count | **corrected** |
|---|---|---|
| Stations | 51 | **55** |
| Districts with ≥1 station | 31 of 36 | **35 of 36** |
| Single-station districts | 22 (71%) | **26 (74%)** |

The lone zero is `Dera Ghazi Khan`, which appears to be a duplicate of `DG Khan`
— and `DG Khan` has a station. **In practice every district in the system has at
least one monitor.**

This kills the monitor-desert framing completely and for the second time. The
representativeness question is now the entire project.

**Method note:** the district list must come from `/api/districts`, never from a
boundary file. The first enumeration silently missed four districts because of
this, and reported a station count 4 too low.
