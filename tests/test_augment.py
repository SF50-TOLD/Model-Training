import random
import re

from tests.factories import declared, effect, extraction, length
from training.augment import variants

PROMPT = "Location: KXYZ\n\nRWY 16/34 CLSD FIRST 1,500FT RWY 16. THR 16 DSPLCD 1500FT. RWY 16 TORA 6000FT."


def label():
    return extraction(
        effect(
            "16",
            "partial",
            closedLength=length(1500),
            closedEnd="thresholdEnd",
            thresholdDisplacement=length(1500),
            declaredDistances=declared(TORA=length(6000)),
        ),
    )


def test_renumbers_and_rescales_text_and_label_alike():
    for text, variant in variants(PROMPT, label(), 3, random.Random(0)):
        rewritten = variant["effects"][0]
        runway, pair = rewritten["runway"], text.split("RWY ")[1].split(" ")[0]
        assert pair.split("/")[0] == runway
        assert f"{rewritten['declaredDistances']['TORA']['value']}FT" in text
        assert f"{rewritten['closedLength']['value']:,}FT" in text
        assert not re.search(r"(?<!\d)16(?!\d)", text)


def test_leaves_the_original_unchanged():
    original = label()
    variants(PROMPT, original, 3, random.Random(0))
    assert original == label()


def test_makes_no_variant_when_a_stated_value_is_not_in_the_text():
    unrelated = extraction(effect("16", thresholdDisplacement=length(999)))
    assert variants(PROMPT, unrelated, 3, random.Random(0)) == []
