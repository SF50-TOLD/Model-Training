import random
import re

from notam_gold.schema import validate
from training.synthetic import examples


def _numbers(value) -> set[int]:
    if isinstance(value, dict):
        return set().union(*map(_numbers, value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*map(_numbers, value)) if value else set()
    return {value} if isinstance(value, int) and not isinstance(value, bool) else set()


def test_every_label_is_valid_and_states_only_numbers_its_text_does():
    for prompt, label in examples(200, random.Random(0)):
        assert validate(label) == []
        written = {int(n) for n in re.findall(r"\d+", prompt)}
        assert _numbers(label) <= written, prompt
