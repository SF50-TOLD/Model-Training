import pytest

from tests.factories import contaminant, declared, effect, extraction, length, obstacle, surface
from training import reading_format


def round_trip(value):
    return reading_format.decode(reading_format.encode(value))


def test_cancellation_and_nothing_are_single_words():
    assert reading_format.encode(extraction(isCanceled=True)) == "CNL"
    assert reading_format.encode(extraction()) == "NIL"


def test_writes_only_what_is_stated_in_a_fixed_order():
    pair = effect("09R/27L", "partial", closedLength=length(1713), closedEnd="W")
    direction = effect("09R", declaredDistances=declared(TORA=length(6787), LDA=length(6100)))
    assert reading_format.encode(extraction(pair, direction)) == (
        "RWY 09R DD 6787ft - - 6100ft\nRWY 09R/27L CLSD PART LEN 1713ft END W"
    )


def test_writes_contaminants_with_third_coverage_and_depth():
    condition = surface([5, 5, 3], [contaminant("wet", 1, 100), contaminant("drySnow", 2, 30, length(0.125, "in"))])
    assert reading_format.encode(extraction(effect("16", surfaceCondition=condition))) == (
        "RWY 16 SFC CC 5/5/3 wet@1%100,drySnow@2%30~0.125in"
    )


@pytest.mark.parametrize(
    "value",
    [
        extraction(
            effect(
                None,
                obstacle=obstacle(
                    heightMSL=length(114),
                    distance=length(2.2, "nm"),
                    distanceReference="JFK",
                    latitude=40.651667,
                    longitude=-73.825278,
                ),
            )
        ),
        extraction(
            effect(
                "27",
                thresholdDisplacement=length(200, "m"),
                declaredDistances=declared(TORA=length(690, "m"), LDA=length(690, "m")),
            )
        ),
        extraction(effect("08/26", surfaceCondition=surface(None, []))),
        extraction(effect("34", "partial", closedLength=length(1500), closedEnd="thresholdEnd")),
    ],
)
def test_reads_back_exactly_what_it_writes(value):
    assert round_trip(value) == value


def test_keeps_a_reference_on_one_line_without_quotes():
    value = extraction(effect(None, obstacle=obstacle(heightAGL=length(60), distanceReference='APCH END\n"RWY" 03L')))
    assert round_trip(value)["effects"][0]["obstacle"]["distanceReference"] == "APCH END 'RWY' 03L"


def test_rejects_text_outside_the_format():
    with pytest.raises(ValueError):
        reading_format.decode("RWY 09 DTHR 300yd")


def test_copies_a_position_as_the_notam_writes_it():
    value = extraction(effect(None, obstacle=obstacle(heightAGL=length(65), latitude=52.6075, longitude=-0.488333)))
    text = "CRANE OPR PSN 523627N 0002918W (RAF WITTERING) 65FT AGL"
    written = reading_format.encode(value, text)
    assert written == "RWY * OBST AGL 65ft POS 523627N 0002918W"
    assert reading_format.decode(written) == value


def test_writes_decimal_degrees_when_the_text_has_no_matching_position():
    value = extraction(effect(None, obstacle=obstacle(heightAGL=length(65), latitude=52.6075, longitude=-0.488333)))
    assert reading_format.encode(value, "CRANE 65FT AGL").endswith("POS 52.6075 -0.488333")
