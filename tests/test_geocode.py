"""Tests for geocoding.

The property that matters: a coordinate outside its district must never be
accepted. A missing station is excluded from the analysis; a wrongly placed one
silently corrupts it.
"""

from __future__ import annotations

import json

from downwind import geocode

# A unit square around (74, 31) standing in for a district.
SQUARE = {
    "type": "Polygon",
    "coordinates": [[[73.5, 30.5], [74.5, 30.5], [74.5, 31.5], [73.5, 31.5], [73.5, 30.5]]],
}
POLYGONS = {"Testland": SQUARE}


def fake_opener(results_by_query):
    def _open(url: str) -> bytes:
        for fragment, payload in results_by_query.items():
            if fragment.replace(" ", "+") in url.replace("%20", "+").replace("%2C", ","):
                return json.dumps(payload).encode()
        return b"[]"

    return _open


def test_point_in_ring_inside_and_outside():
    ring = SQUARE["coordinates"][0]
    assert geocode.point_in_ring(74.0, 31.0, ring) is True
    assert geocode.point_in_ring(70.0, 31.0, ring) is False


def test_check_in_district_returns_none_when_no_polygon_exists():
    """Kot Addu, Murree, Wazirabad and DG Khan post-date the boundary file.

    Unverifiable must not be recorded as verified, nor as refuted.
    """
    assert geocode.check_in_district(31.0, 74.0, "Kot Addu", POLYGONS) is None


def test_a_result_outside_the_district_is_rejected():
    opener = fake_opener(
        {
            "Somewhere": [
                {"lat": "24.86", "lon": "67.00", "type": "city", "display_name": "Karachi"}
            ]
        }
    )
    got = geocode.locate(
        "Somewhere", "Testland", POLYGONS, opener=opener, sleep=lambda _s: None
    )
    assert got is None


def test_a_result_inside_the_district_is_accepted():
    opener = fake_opener(
        {
            "Somewhere": [
                {"lat": "31.0", "lon": "74.0", "type": "town", "display_name": "Somewhere"}
            ]
        }
    )
    got = geocode.locate(
        "Somewhere", "Testland", POLYGONS, opener=opener, sleep=lambda _s: None
    )
    assert got is not None
    assert got.in_district_polygon is True
    assert got.precision == "neighbourhood"


def test_the_first_inside_result_wins_over_an_earlier_outside_one():
    """Both candidates name the station; only one is in the district."""
    opener = fake_opener(
        {
            "Somewhere": [
                {
                    "lat": "24.8",
                    "lon": "67.0",
                    "type": "city",
                    "display_name": "Somewhere, Sindh, Pakistan",
                },
                {
                    "lat": "31.1",
                    "lon": "74.1",
                    "type": "city",
                    "display_name": "Somewhere, Testland, Pakistan",
                },
            ]
        }
    )
    got = geocode.locate(
        "Somewhere", "Testland", POLYGONS, opener=opener, sleep=lambda _s: None
    )
    assert got.matched_name == "Somewhere, Testland, Pakistan"


def test_unverifiable_result_is_kept_but_flagged():
    opener = fake_opener(
        {
            "Somewhere": [
                {"lat": "31.0", "lon": "74.0", "type": "city", "display_name": "Somewhere"}
            ]
        }
    )
    got = geocode.locate(
        "Somewhere", "Nowhere", POLYGONS, opener=opener, sleep=lambda _s: None
    )
    assert got is not None
    assert got.in_district_polygon is None


def test_candidate_queries_are_ordered_and_deduplicated():
    queries = geocode.candidate_queries("Attok", "Attock")
    assert queries[0].startswith("Attock, Attock")  # the hint is applied
    assert len(queries) == len(set(queries))
    assert queries[-1] == "Attock, Punjab, Pakistan"


def test_dc_office_names_are_expanded():
    assert "Deputy Commissioner" in geocode.candidate_queries("DC Office Kasur", "Kasur")[0]


def test_precision_classification():
    assert geocode.classify_precision({"addresstype": "university"}) == "venue"
    assert geocode.classify_precision({"type": "suburb"}) == "neighbourhood"
    assert geocode.classify_precision({"type": "city"}) == "settlement"
    assert geocode.classify_precision({"type": "wormhole"}) == "unknown"


def test_a_failing_lookup_yields_nothing_rather_than_raising():
    def boom(_url: str) -> bytes:
        raise OSError("network down")

    assert (
        geocode.locate("X", "Testland", POLYGONS, opener=boom, sleep=lambda _s: None)
        is None
    )


def test_name_mismatch_is_rejected_even_inside_the_district():
    """The Talagang failure: right district, wrong town, 38 km away.

    A polygon check proves a point is in the district, never that it is the
    place asked for.
    """
    opener = fake_opener(
        {
            "Talagang": [
                {
                    "lat": "31.0",
                    "lon": "74.0",
                    "type": "city",
                    "display_name": "Chakwal, Punjab, Pakistan",
                }
            ]
        }
    )
    got = geocode.locate(
        "Talagang", "Testland", POLYGONS, opener=opener, sleep=lambda _s: None
    )
    # Only the district fallback may answer, and it must say so.
    assert got is None or got.precision == geocode.DISTRICT_CENTROID


def test_name_matching():
    assert geocode.name_matches("Talagang", "Talagang, Chakwal, Pakistan") is True
    assert geocode.name_matches("Talagang", "Chakwal, Punjab, Pakistan") is False
    # Hints are applied before matching: the API spells it "Attok".
    assert geocode.name_matches("Attok", "Attock City, Punjab") is True


def test_district_fallback_is_labelled_not_disguised():
    """A city centroid must never be recorded as if it were the station."""
    opener = fake_opener(
        {
            "Testland,+Punjab": [
                {
                    "lat": "31.0",
                    "lon": "74.0",
                    "type": "city",
                    "display_name": "Testland, Punjab, Pakistan",
                }
            ]
        }
    )
    got = geocode.locate(
        "Some Unfindable Office", "Testland", POLYGONS, opener=opener, sleep=lambda _s: None
    )
    assert got is not None
    assert got.precision == geocode.DISTRICT_CENTROID


def test_english_names_are_requested():
    """Urdu display names cannot be checked against the queried station name."""
    captured = {}

    def _open(url: str) -> bytes:
        captured["url"] = url
        return b"[]"

    geocode.locate("X", "Testland", POLYGONS, opener=_open, sleep=lambda _s: None)
    assert "accept-language=en" in captured["url"]


def test_a_road_named_after_the_town_is_rejected():
    """The second Talagang failure.

    "Talagang-Chakwal Road" carries the station's name and lies in the right
    district, so both earlier guards passed it -- while sitting 38 km away in
    Chakwal city. A road is never a station location.
    """
    assert geocode.is_linear_feature({"class": "highway", "type": "trunk"}) is True
    assert geocode.is_linear_feature({"class": "place", "type": "town"}) is False

    opener = fake_opener(
        {
            "Talagang": [
                {
                    "lat": "31.0",
                    "lon": "74.0",
                    "class": "highway",
                    "type": "trunk",
                    "display_name": "Talagang-Chakwal Road, Chakwal, Pakistan",
                }
            ]
        }
    )
    got = geocode.locate(
        "Talagang", "Testland", POLYGONS, opener=opener, sleep=lambda _s: None
    )
    assert got is None


def test_a_district_free_query_is_tried_before_the_centroid_fallback():
    """Talagang is filed under Chakwal but is its own district now."""
    queries = geocode.candidate_queries("Talagang", "Chakwal")
    assert "Talagang, Punjab, Pakistan" in queries
    assert queries.index("Talagang, Punjab, Pakistan") < queries.index(
        "Chakwal, Punjab, Pakistan"
    )


def test_linear_features_are_caught_without_a_category_field():
    """jsonv2 reports the class as "category" and often omits it entirely.

    The first version of this guard checked only "class", so it never fired on
    a real response and Talagang stayed 38 km wrong through a passing suite.
    """
    assert geocode.is_linear_feature({"type": "trunk"}) is True
    assert geocode.is_linear_feature({"category": "highway", "type": "trunk"}) is True
    assert geocode.is_linear_feature({"type": "city"}) is False
    assert geocode.is_linear_feature({"type": "administrative"}) is False
