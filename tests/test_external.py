import pytest

from notam_gold.external import deel_record, evolve_record, polymtl_record

AIRCRAFT = "{'738': [737, 'C', 35.8], '744': [747, 'D', 64.93]}"
LOCATIONS = {"NYL": "KNYL", "WIDE": "YBBN"}


def polymtl_row(**overrides):
    return {
        "id": "B2239/20",
        "location": "LFOK",
        "startdate": "2020-06-01T00:00:00.000Z",
        "enddate": "2020-08-31T23:59:00.000Z",
        "message": " VATRY CTR AND AD CONTROL HOURS OF OPS: EVERY DAY 0630-1100, \r\n1200-1700",
    } | overrides


def test_evolve_notams_keep_their_a_item_location_and_e_item_text():
    raw = f"A) CYHM E)FIRST 2120FT RWY 06 CLSD DUE CONST.\nTHR 06 IS DISPLACED 2120FT. \n)\nNNNN\n{AIRCRAFT}"

    record = evolve_record(raw)

    assert record["icao_location"] == "CYHM"
    assert record["notam_text"] == "FIRST 2120FT RWY 06 CLSD DUE CONST.\nTHR 06 IS DISPLACED 2120FT."
    assert record["id"] == f"CYHM {record['notam_id']}"
    assert (record["effective_start"], record["nms_type"], record["source"]) == (None, None, "notam-evolve-2024")


def test_evolve_notams_drop_lower_and_upper_limits():
    record = evolve_record("A) NZPM E)RWY 25 CLSD F)SFC G)500FT\n)\nNNNN")
    assert record["notam_text"] == "RWY 25 CLSD"


def test_identical_evolve_texts_share_an_id_and_different_ones_dont():
    texts = ("RWY 04R CLSD", "RWY 04R CLSD", "RWY 04L CLSD")
    first, again, other = (evolve_record(f"A) EFHK E){text}\n)\nNNNN") for text in texts)
    assert first["id"] == again["id"] != other["id"]


def test_evolve_notams_without_an_a_item_are_dropped():
    assert evolve_record("E)ROCKET FRNG WILL TAKE PLACE RADIUS 5NM CENTRE 161918N1004312E") is None


@pytest.mark.parametrize(
    ("text", "location", "expected"),
    [
        ("NYL RWY 35 CLSD LDG", "KNYL", "NYL RWY 35 CLSD LDG"),
        ("A) EGLL E)RWY 09L THR DISPLACED 300M", "EGLL", "RWY 09L THR DISPLACED 300M"),
        (
            "A078118 NOTAMN Q)KZBWQMRXX A)KPBG B)1806271400 C)1809250800 E)RWY 35 THR DISPLACED 4751FT",
            "KPBG",
            "RWY 35 THR DISPLACED 4751FT",
        ),
    ],
)
def test_deel_notams_take_the_location_their_text_names(text, location, expected):
    record = deel_record(text, LOCATIONS)
    assert (record["icao_location"], record["notam_text"], record["source"]) == (location, expected, "deel-ai-notam")


@pytest.mark.parametrize(
    "text",
    ["ILS RWY 09 U/S.", "WIDE BAY AIRSPACE R685AB ACT", "ZONE A) EGLL E)RWY 27R CLSD"],
)
def test_deel_notams_naming_no_location_unambiguously_are_dropped(text):
    assert deel_record(text, LOCATIONS) is None


def test_polymtl_notams_become_api_shaped_records():
    record = polymtl_record(polymtl_row(location="LFOK\n"))

    assert record == {
        "id": "LFOK B2239/20",
        "notam_id": "B2239/20",
        "icao_location": "LFOK",
        "effective_start": "2020-06-01T00:00:00.000Z",
        "effective_end": "2020-08-31T23:59:00.000Z",
        "notam_text": "VATRY CTR AND AD CONTROL HOURS OF OPS: EVERY DAY 0630-1100, \n1200-1700",
        "nms_type": None,
        "source": "polymtl-2020",
    }


def test_polymtl_times_with_the_day_in_the_hour_field_are_repaired():
    record = polymtl_record(polymtl_row(startdate="2020-01-14T14:23:4200.000Z", enddate=None))
    assert (record["effective_start"], record["effective_end"]) == ("2020-01-14T23:42:00.000Z", None)


def test_polymtl_rows_without_a_message_or_location_are_dropped():
    assert polymtl_record(polymtl_row(message=" ")) is None
    assert polymtl_record(polymtl_row(location=None)) is None
