import pytest

from tests.factories import (
    contaminant,
    declared,
    effect,
    extraction,
    height,
    length,
    obstacle,
    partial,
    reference,
    surface,
)
from training import reading_format


def round_trip(value):
    return reading_format.decode(reading_format.encode(value))


def test_cancellation_and_nothing_are_single_words():
    assert reading_format.encode(extraction(isCanceled=True)) == "CNL"
    assert reading_format.encode(extraction()) == "NIL"


def test_writes_only_what_is_stated_in_a_fixed_order():
    first = effect(
        "09R", partialClosure=partial(length(1713), "W"), declaredDistances=declared(length(6787), length(6100))
    )
    second = effect("27L", partialClosure=partial(length(1713), "W"))
    assert reading_format.encode(extraction(second, first)) == (
        "RWY 09R PART 1713ft END W TORA 6787ft LDA 6100ft\nRWY 27L PART 1713ft END W"
    )


def test_writes_which_operations_a_runway_is_closed_to():
    value = extraction(effect("24", "both"), effect("06", "landing"), effect("12", "takeoff"))
    assert reading_format.encode(value) == "RWY 06 CLSD LDG\nRWY 12 CLSD TKOF\nRWY 24 CLSD"


def test_writes_contaminants_with_coverage_and_depth():
    condition = surface([5, 5, 3], [contaminant("wet", 100), contaminant("drySnow", 30, length(0.125, "in"))])
    assert reading_format.encode(extraction(effect("16", surfaceCondition=condition))) == (
        "RWY 16 SFC CC 5/5/3 drySnow%30~0.125in,wet%100"
    )


def test_obstacles_follow_effects():
    value = extraction(
        effect("19", thresholdDisplacement=length(200, "m")),
        obstacles=[
            obstacle(height(114, datum="MSL"), length(2.2, "nm"), reference("ARP"), "WNW"),
            obstacle(height(440, datum="MSL"), length(4739), reference("departureEnd", "19")),
        ],
    )
    assert reading_format.encode(value) == (
        "RWY 19 DTHR 200m\nOBST MSL 114ft DIST 2.2nm ARP DIR WNW\nOBST MSL 440ft DIST 4739ft DER 19"
    )


@pytest.mark.parametrize(
    "value",
    [
        extraction(obstacles=[obstacle(height(60), length(1, "nm"), reference("threshold", "03L"), 114.5)]),
        extraction(obstacles=[obstacle(height(100, "m", "AGL"), length(300, "m"), reference("other"))]),
        extraction(obstacles=[obstacle(distance=length(0.5, "nm"), reference=reference("ARP"), direction=0)]),
        extraction(
            effect(
                "27",
                thresholdDisplacement=length(200, "m"),
                declaredDistances=declared(length(690, "m"), length(690, "m")),
            )
        ),
        extraction(effect("08", surfaceCondition=surface(None, [])), effect("26", surfaceCondition=surface([3], []))),
        extraction(effect("34", partialClosure=partial(length(1500), "thresholdEnd"))),
        extraction(effect("34", partialClosure=partial())),
        extraction(effect("34", partialClosure=partial(end="27L"))),
        extraction(effect("04", "landing", declaredDistances=declared(TORA=length(5000)))),
        extraction(effect(None, "both")),
    ],
)
def test_reads_back_exactly_what_it_writes(value):
    assert round_trip(value) == value


@pytest.mark.parametrize(
    "text",
    [
        "RWY 09 DTHR 300yd",
        "OBST MSL 114ft DIST 2.2nm",
        "OBST MSL 114ft DIST 2.2nm DER",
        "RWY 09 DD TORA 5000ft",
        "RWY 09 SFC wet@1%100",
        "RWY 09 SFC",
        "RWY 09 DTHR",
        "OBST AGL",
        "RWY",
    ],
)
def test_rejects_text_outside_the_format(text):
    with pytest.raises(ValueError):
        reading_format.decode(text)
