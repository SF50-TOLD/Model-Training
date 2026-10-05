"""Label-preserving variants of training NOTAMs, for the fields the corpus has few examples of.

A variant renumbers the runway and rescales the lengths a NOTAM states, and makes exactly the same
change to its label: a reciprocal pair stays reciprocal (`09R/27L` → `14L/32R`), and each length is
rewritten in the same form it was written in (`1,713 FT` → `2,480 FT`). A variant is kept only when
every designator and length in the label was found in the text and replaced, so the label never
disagrees with its text. Nothing else in the NOTAM changes, so the model learns to copy values rather
than to recognise particular NOTAMs.
"""

import copy
import random
import re

MEASURED_FIELDS = ("partialClosure.length", "thresholdDisplacement")
DECLARED = ("TORA", "LDA")
_DESIGNATOR = re.compile(r"(?<![0-9A-Z])(\d{1,2})([LCR]?)(?![0-9])")
_OPPOSITE_SIDE = {"L": "R", "R": "L", "C": "C", "": ""}


def variants(prompt: str, label: dict, count: int, rng: random.Random) -> list[tuple[str, dict]]:
    """Up to ``count`` variants of one labelled NOTAM."""
    made = []
    for _ in range(count * 3):
        if len(made) == count:
            break
        variant = _variant(prompt, label, rng)
        if variant and variant not in made:
            made.append(variant)
    return made


def _variant(prompt: str, label: dict, rng: random.Random) -> tuple[str, dict] | None:
    location, _, text = prompt.partition("\n\n")
    label = copy.deepcopy(label)
    text = _renumber_runways(text, label, rng)
    if text is None:
        return None
    text = _rescale_lengths(text, label, rng)
    if text is None:
        return None
    return f"{location}\n\n{text}", label


def _directions(label: dict) -> set[str]:
    """Every runway direction the label names: as a runway, a closed end or an obstacle's reference."""
    effects, obstacles = label["effects"], label["obstacles"]
    designators = {e["runway"] for e in effects} | {_closed_end(e) for e in effects}
    designators |= {o["reference"]["runway"] for o in obstacles if o["reference"]}
    return designators - {None}


def _closed_end(effect: dict) -> str | None:
    end = (effect["partialClosure"] or {}).get("end")
    return end if end and _DESIGNATOR.fullmatch(end) else None


def _renumber_runways(text: str, label: dict, rng: random.Random) -> str | None:
    directions = _directions(label)
    if not directions:
        return text
    offset = rng.randint(1, 17)
    swap_sides = rng.random() < 0.5

    def mapped(number: int, side: str) -> str:
        new = (number - 1 + offset) % 36 + 1
        return f"{new:02d}{_OPPOSITE_SIDE[side] if swap_sides else side}"

    mapping = {d: mapped(int(d[:2]), d[2:]) for d in directions}
    written_numbers = {str(int(d[:2])) for d in directions} | {d[:2] for d in directions}
    replaced = set()

    def substitute(match: re.Match) -> str:
        number, side = match.group(1), match.group(2)
        key = f"{int(number):02d}{side}"
        if key not in mapping or number not in written_numbers:
            return match.group(0)
        replaced.add(key)
        new = mapping[key]
        return new if len(number) == 2 else new.lstrip("0") if new[0] == "0" else new

    new_text = _substitute_near_runway_words(text, substitute)
    if replaced != directions or _mentions_any(new_text, directions):
        return None
    for effect in label["effects"]:
        if effect["runway"]:
            effect["runway"] = mapping[effect["runway"]]
        if _closed_end(effect):
            effect["partialClosure"]["end"] = mapping[effect["partialClosure"]["end"]]
    for obstacle in label["obstacles"]:
        if obstacle["reference"] and obstacle["reference"]["runway"]:
            obstacle["reference"]["runway"] = mapping[obstacle["reference"]["runway"]]
    return new_text


def _substitute_near_runway_words(text: str, substitute) -> str:
    """Replaces designators only where the text says they are runways (`RWY 09R/27L`, `RWY 27`)."""
    runway_phrase = re.compile(
        r"\b(?:RWYS?|RUNWAYS?|D?THR|THRESHOLD)\s*((?:\d{1,2}[LCR]?)(?:\s*[/-]\s*\d{1,2}[LCR]?)?)"
    )

    def phrase(match: re.Match) -> str:
        designators = _DESIGNATOR.sub(substitute, match.group(1))
        return match.group(0).replace(match.group(1), designators)

    return runway_phrase.sub(phrase, text)


def _mentions_any(text: str, directions: set[str]) -> bool:
    """Whether an original designator is still written anywhere as a standalone number."""
    for direction in directions:
        number, side = str(int(direction[:2])), direction[2:]
        written = rf"(?:0?{number}){side}" if side else rf"0?{number}"
        if re.search(rf"(?<![\d.:])(?:{written})(?![\d])", text):
            return True
    return False


def _measures(label: dict) -> list[dict]:
    found = []
    for effect in label["effects"]:
        found += [measure for path in MEASURED_FIELDS if (measure := _at(effect, path))]
        if effect["declaredDistances"]:
            found += [effect["declaredDistances"][k] for k in DECLARED if effect["declaredDistances"][k]]
    return found


def _at(effect: dict, path: str) -> dict | None:
    """The measure at a dotted ``path`` such as ``partialClosure.length``, or ``None`` anywhere along it."""
    value = effect
    for key in path.split("."):
        if value is None:
            return None
        value = value[key]
    return value


def _rescale_lengths(text: str, label: dict, rng: random.Random) -> str | None:
    measures = _measures(label)
    values = sorted({m["value"] for m in measures if float(m["value"]).is_integer()}, reverse=True)
    if len(values) != len({m["value"] for m in measures}):
        return None
    if not values:
        return text
    factor = rng.uniform(0.6, 1.6)
    mapping = {v: max(1, round(v * factor / 5) * 5) for v in values}
    patterns = {v: re.compile(rf"(?<![\d,.]){_written(int(v))}(?![\d,])") for v in values}
    if not all(p.search(text) for p in patterns.values()):
        return None
    # One pass over every value at once, so a rewritten value is never rewritten again.
    either = re.compile("|".join(p.pattern for p in patterns.values()))
    text = either.sub(lambda m: _rewrite(m.group(0), mapping[int(m.group(0).replace(",", ""))]), text)
    for measure in measures:
        measure["value"] = mapping[measure["value"]]
    return text


def _written(value: int) -> str:
    """A pattern for ``value`` with or without a thousands separator."""
    plain = str(value)
    grouped = f"{value:,}"
    return f"(?:{re.escape(grouped)}|{re.escape(plain)})" if grouped != plain else re.escape(plain)


def _rewrite(original: str, value: int) -> str:
    return f"{value:,}" if "," in original else str(value)
