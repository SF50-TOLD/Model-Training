import pytest

from tests.factories import declared, effect, extraction, height, length, obstacle, partial, reference
from training.evaluate import Outcome, outcomes, summarize

GOLD = extraction(
    effect("09R", partialClosure=partial(length(1713), "W"), declaredDistances=declared(length(6787), length(6100))),
    effect("27L", "landing"),
    obstacles=[obstacle(height(114, datum="MSL"), length(2.2, "nm"), reference("ARP"), "WNW")],
)


def test_a_perfect_reading_is_correct_wherever_gold_states_something():
    scored = outcomes(GOLD, GOLD)
    assert set(scored.values()) == {Outcome.CORRECT}
    assert ("09R", "TORA") in scored and ("27L", "closure") in scored and ("obstacles", "height") in scored


def test_missed_wrong_and_invented_values_are_told_apart():
    read = extraction(
        effect("09R", partialClosure=partial(length(1713), "E"), declaredDistances=declared(length(6000))),
        effect("27L", "landing", thresholdDisplacement=length(300)),
    )
    scored = outcomes(GOLD, read)
    assert scored[("09R", "partialClosure.end")] == Outcome.WRONG
    assert scored[("09R", "TORA")] == Outcome.WRONG
    assert scored[("09R", "LDA")] == Outcome.MISSED
    assert scored[("27L", "thresholdDisplacement")] == Outcome.INVENTED
    assert scored[("obstacles", "height")] == Outcome.MISSED


def test_a_closure_the_gold_lacks_is_invented_and_an_unreadable_reading_misses_everything():
    assert (
        outcomes(extraction(effect("09", "none", thresholdDisplacement=length(1))), extraction(effect("09", "both")))[
            ("09", "closure")
        ]
        == Outcome.INVENTED
    )
    unreadable = outcomes(GOLD, None)
    assert set(unreadable.values()) == {Outcome.MISSED}


def test_summary_gives_recall_and_safety_per_field_and_whole_notam_rates():
    read = extraction(
        effect("09R", partialClosure=partial(length(1713), "W"), declaredDistances=declared(length(6787), length(6100)))
    )
    summary = summarize(
        [(GOLD, GOLD), (GOLD, read), (extraction(), extraction()), (extraction(), extraction(effect("05", "both")))]
    )
    assert summary["fields"]["TORA"] == {"recall": 1.0, "safety": 1.0, "stated": 2}
    assert summary["fields"]["closure"] == {"recall": 0.5, "safety": pytest.approx(2 / 3), "stated": 2}
    assert summary["notams"]["exact"] == 0.5
    assert summary["notams"]["staysSilent"] == 0.5
    assert summary["notams"]["hazardous"] == 0.25


def test_closing_more_operations_than_gold_is_cautious_but_fewer_is_hazardous():
    landing = extraction(effect("04R", "landing"))
    over = summarize([(landing, extraction(effect("04R", "both")))])
    under = summarize([(extraction(effect("04R", "both")), extraction(effect("04R", "landing")))])
    assert over["notams"]["hazardous"] == 0
    assert under["notams"]["hazardous"] == 1
