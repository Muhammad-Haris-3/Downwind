"""Locate the stations the aqicn cross-match could not place.

Every coordinate produced here is checked against the district polygon the
station is supposed to sit in. A geocoder will cheerfully return a plausible
point in the wrong province, and an unverified coordinate is worse than a
missing one: a missing station is excluded from the analysis, a wrong one
silently corrupts it.

Each result carries how it was obtained and how precise it is. A district
centroid standing in for a station is a real limitation, and downstream code
must be able to see it rather than infer it.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

NOMINATIM = "https://nominatim.openstreetmap.org/search"

# Nominatim's usage policy requires an identifying User-Agent and at most one
# request per second. Thirteen lookups, run once.
GEOCODE_HEADERS = {
    "User-Agent": "Downwind/0.1 (air quality research; github.com/Muhammad-Haris-3/Downwind)",
    "Accept": "application/json",
}
RATE_LIMIT_SECONDS = 1.1

# Station names are operator shorthand, not placenames. These expansions are
# the interpretation being applied, written down so it can be argued with.
NAME_HINTS: dict[str, str] = {
    "Attok": "Attock",  # the API's spelling; the town is Attock
    "DC Office Kasur": "Deputy Commissioner Office, Kasur",
    "DC Office Muzaffargarh": "Deputy Commissioner Office, Muzaffargarh",
    "DC Office DG Khan": "Deputy Commissioner Office, Dera Ghazi Khan",
    "M. Nawaz Sharif University of Engineering & Technology Multan": (
        "Muhammad Nawaz Sharif University of Engineering and Technology, Multan"
    ),
    "Model Town, Lahore": "Model Town, Lahore",
}

# Precision, inferred from what Nominatim says it matched.
# A district-only query returns the district centroid. That is a legitimate
# last resort, but it must be labelled as one rather than inheriting whatever
# type Nominatim happens to report for the centroid.
DISTRICT_CENTROID = "district_centroid"

# A road named after a town sits wherever the road is, not where the town is.
# "Talagang-Chakwal Road" matched for Talagang and put the station 38 km away
# in Chakwal city, carrying the right name the whole way.
LINEAR_CLASSES = {"highway", "railway", "waterway", "route"}

# jsonv2 reports the class under "category", and often omits it entirely --
# leaving only "type". These are OSM highway values, which identify a road even
# when no category field is present at all.
LINEAR_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "service", "track", "road", "living_street", "motorway_link",
    "trunk_link", "primary_link", "secondary_link", "tertiary_link", "rail",
}

VENUE_TYPES = {"office", "building", "university", "college", "amenity", "school"}
AREA_TYPES = {"suburb", "neighbourhood", "quarter", "residential", "town", "village"}
SETTLEMENT_TYPES = {"city", "administrative", "municipality", "county", "state"}


@dataclass
class Located:
    station_name: str
    district: str
    lat: float
    lon: float
    precision: str
    source: str
    query: str
    matched_name: str
    in_district_polygon: bool | None


def candidate_queries(station_name: str, district: str) -> list[str]:
    """Query strings to try, most specific first.

    Deterministic, so a rerun produces the same lookups and the same answer.
    """
    hinted = NAME_HINTS.get(station_name, station_name)
    base = hinted.split(",")[0].strip()
    queries = [
        f"{hinted}, {district}, Punjab, Pakistan",
        f"{base}, {district}, Punjab, Pakistan",
        # Without the district. Some stations sit in a tehsil that has since
        # become its own district while the API still files it under the old
        # one, and naming the old district drags the match toward its capital.
        f"{base}, Punjab, Pakistan",
        f"{district}, Punjab, Pakistan",
    ]
    seen: set[str] = set()
    return [q for q in queries if not (q in seen or seen.add(q))]


def classify_precision(payload: dict[str, Any]) -> str:
    """How tightly the returned point pins the station down."""
    for key in ("addresstype", "type", "class"):
        value = str(payload.get(key, "")).lower()
        if value in VENUE_TYPES:
            return "venue"
        if value in AREA_TYPES:
            return "neighbourhood"
        if value in SETTLEMENT_TYPES:
            return "settlement"
    return "unknown"


def is_linear_feature(payload: dict[str, Any]) -> bool:
    """Roads, railways and canals are never a monitoring station's location."""
    if str(payload.get("category", payload.get("class", ""))).lower() in LINEAR_CLASSES:
        return True
    return str(payload.get("type", "")).lower() in LINEAR_TYPES


def name_matches(station_name: str, matched_name: str) -> bool:
    """Does the geocoder's answer actually mention the place we asked about?

    Guards the failure this check was added for: querying "Talagang, Chakwal"
    returned a point at Chakwal city, thirty-eight kilometres away, and passed
    the district-polygon test because Chakwal city is genuinely in Chakwal.
    A polygon check proves a point is in the right district, never that it is
    the right place within it.
    """
    base = NAME_HINTS.get(station_name, station_name).split(",")[0].strip().lower()
    haystack = matched_name.lower()
    tokens = [t for t in base.replace("&", " ").split() if len(t) > 3]
    if not tokens:
        return base in haystack
    return any(token in haystack for token in tokens)


def _search(query: str, *, opener: Callable[[str], bytes]) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "countrycodes": "pk",
            "limit": "5",
            "addressdetails": "1",
            # Without this, display_name comes back in Urdu and cannot be
            # checked against the station name we asked for.
            "accept-language": "en",
        }
    )
    return json.loads(opener(f"{NOMINATIM}?{params}").decode("utf-8"))


def _http_open(url: str) -> bytes:
    request = urllib.request.Request(url, headers=GEOCODE_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


# --- district polygon check -------------------------------------------------


def _rings(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    if geometry["type"] == "Polygon":
        yield geometry["coordinates"][0]
    elif geometry["type"] == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            yield polygon[0]


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray casting. Ring coordinates are [lon, lat], as GeoJSON requires."""
    inside = False
    count = len(ring)
    for i in range(count):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % count][0], ring[(i + 1) % count][1]
        if (y1 > lat) != (y2 > lat):
            x_at = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_at:
                inside = not inside
    return inside


def load_district_polygons(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        feature["properties"]["districts"]: feature["geometry"]
        for feature in data["features"]
        if feature["properties"].get("province_territory") == "Punjab"
    }


def check_in_district(
    lat: float, lon: float, district: str, polygons: dict[str, dict[str, Any]]
) -> bool | None:
    """True/False if the district has a polygon, None if it has none.

    Four districts in the API — Kot Addu, Murree, Wazirabad, DG Khan — do not
    appear in the boundary file, which predates their creation. Unverifiable is
    not the same as wrong, and must not be recorded as either.
    """
    geometry = polygons.get(district)
    if geometry is None:
        return None
    return any(point_in_ring(lon, lat, ring) for ring in _rings(geometry))


# --- driver -----------------------------------------------------------------


def locate(
    station_name: str,
    district: str,
    polygons: dict[str, dict[str, Any]],
    *,
    opener: Callable[[str], bytes] = _http_open,
    sleep: Callable[[float], None] = time.sleep,
) -> Located | None:
    """Try each candidate query until one lands inside the right district.

    A result outside the district is rejected rather than kept with a warning.
    Falling back to a plainly wrong point would put a station in the analysis
    at a location the analysis then trusts.
    """
    best: Located | None = None
    queries = candidate_queries(station_name, district)
    for index, query in enumerate(queries):
        is_fallback = index == len(queries) - 1
        sleep(RATE_LIMIT_SECONDS)
        try:
            results = _search(query, opener=opener)
        except Exception:  # noqa: BLE001 - a failed lookup is simply no answer
            continue
        for payload in results:
            lat, lon = float(payload["lat"]), float(payload["lon"])
            matched = payload.get("display_name", "")
            inside = check_in_district(lat, lon, district, polygons)

            # A specific query whose answer does not mention the place asked
            # for has drifted to something else. Reject it rather than record
            # a confident-looking coordinate for the wrong town.
            if is_linear_feature(payload):
                continue
            if not is_fallback and not name_matches(station_name, matched):
                continue

            located = Located(
                station_name=station_name,
                district=district,
                lat=lat,
                lon=lon,
                precision=(
                    DISTRICT_CENTROID if is_fallback else classify_precision(payload)
                ),
                source="nominatim",
                query=query,
                matched_name=matched,
                in_district_polygon=inside,
            )
            if inside:
                return located
            if inside is None and best is None:
                # Unverifiable, but not contradicted. Hold it in case nothing
                # better appears.
                best = located
    return best
