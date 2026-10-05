import random
import re

from tests.factories import declared, effect, extraction, length, obstacle, partial, reference
from training.augment import variants

PROMPT = "Location: KXYZ\n\nRWY 16/34 CLSD FIRST 1,500FT RWY 16. THR 16 DSPLCD 1500FT. RWY 16 TORA 6000FT."
REFERENCING_PROMPT = "Location: KXYZ\n\nRWY 16/34 CLSD RWY 34 END. CRANE 430FT BFR THR 16."


def label():
    return extraction(
        effect(
            "16",
            partialClosure=partial(length(1500), "thresholdEnd"),
            thresholdDisplacement=length(1500),
            declaredDistances=declared(TORA=length(6000)),
        ),
    )


def referencing_label():
    return extraction(
        effect("16", partialClosure=partial(end="34")),
        obstacles=[obstacle(distance=length(430), reference=reference("threshold", "16"))],
    )


def test_renumbers_and_rescales_text_and_label_alike():
    for text, variant in variants(PROMPT, label(), 3, random.Random(0)):
        rewritten = variant["effects"][0]
        runway, pair = rewritten["runway"], text.split("RWY ")[1].split(" ")[0]
        assert pair.split("/")[0] == runway
        assert f"{rewritten['declaredDistances']['TORA']['value']}FT" in text
        assert f"{rewritten['partialClosure']['length']['value']:,}FT" in text
        assert not re.search(r"(?<!\d)16(?!\d)", text)


def test_renumbers_a_closed_end_and_an_obstacle_reference_with_the_runway():
    made = variants(REFERENCING_PROMPT, referencing_label(), 3, random.Random(0))
    assert len(made) == 3
    for text, variant in made:
        runway, end = variant["effects"][0]["runway"], variant["effects"][0]["partialClosure"]["end"]
        assert variant["obstacles"][0]["reference"]["runway"] == runway
        assert f"RWY {runway}/{end} CLSD RWY {end} END. CRANE 430FT BFR THR {runway}." in text


def test_leaves_the_original_unchanged():
    original = label()
    variants(PROMPT, original, 3, random.Random(0))
    assert original == label()


def test_makes_no_variant_when_a_stated_value_is_not_in_the_text():
    unrelated = extraction(effect("16", thresholdDisplacement=length(999)))
    assert variants(PROMPT, unrelated, 3, random.Random(0)) == []
