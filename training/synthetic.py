"""Synthetic NOTAMs for a pattern the corpus has no usable examples of.

NAV CANADA publishes a threshold displaced because of an obstacle as one NOTAM stating the
displacement, the obstacle's distance before the threshold and its heights above ground and sea level,
and the declared distances that follow (`THR 01 DISPLACED 663FT DUE OBSTACLE 1770FT BFR THR 01 …
47FT AGL 330FT AMSL`). Every such NOTAM in the corpus is a gold NOTAM or a reissue of one, so training
has none. These are written from that phrasing with invented runways and values, and each label is
built from the same values as its text, so the two can't disagree.

Only training uses them; validation and the gold sets never do.
"""

import random
import textwrap

from notam_gold.prompt import build_prompt

STRATUM = "synthetic_displaced_obstacle"
LOCATIONS = ("CYQT", "CYXU", "CYAM", "CYTS", "CYQA", "CYPQ", "CYXL", "CYBR", "CYQL", "CYYN", "CYKF", "CYOW")
CAUSES = ("OBSTACLE", "OBST", "TREES", "TREE", "CRANE", "CONST EQPT", "TOWER")
MARKINGS = ("", " MARKED BY FLAGS AND LGTD.", " LGTD.", " NOT LGTD.", " MARKED AND LGTD.")
LINE_WIDTH = 66


def examples(count: int, rng: random.Random) -> list[tuple[str, dict]]:
    """``count`` synthetic prompts and their labels."""
    return [_example(rng) for _ in range(count)]


def _example(rng: random.Random) -> tuple[str, dict]:
    displaced, opposite = _runway_pair(rng)
    runway_ft = rng.randint(30, 110) * 100 + rng.choice((0, rng.randint(1, 99)))
    displacement = rng.randint(150, min(2500, runway_ft // 3))
    agl = rng.randint(10, 200)
    msl = agl + rng.randint(20, 2500)
    before_ft = rng.choice((None, rng.randint(200, 3000)))
    first_closed = rng.random() < 0.3

    prose = [
        _displacement_sentence(rng, displaced, displacement, before_ft),
        f"{rng.choice(('', 'APRX '))}{agl}FT AGL {msl}FT AMSL.{rng.choice(MARKINGS)}",
    ]
    effect = _effect(displaced) | {
        "thresholdDisplacement": _ft(displacement),
        "obstacle": _obstacle(agl, msl, before_ft, displaced),
    }
    if first_closed:
        prose.append(f"FIRST {displacement}FT RWY {displaced} CLSD, AVBL AS TWY.")
        effect |= {"closure": "partial", "closedLength": _ft(displacement), "closedEnd": "thresholdEnd"}
    lines = textwrap.wrap(" ".join(prose), LINE_WIDTH)
    effects = [effect]
    if rng.random() < 0.85:
        distances = _declared_distances(rng, displaced, opposite, runway_ft, displacement, first_closed)
        lines += _declared_lines(rng, distances)
        effect["declaredDistances"] = distances[displaced]
        effects.append(_effect(opposite) | {"declaredDistances": distances[opposite]})
    return build_prompt(rng.choice(LOCATIONS), "\n".join(lines)), {"isCanceled": False, "effects": effects}


def _runway_pair(rng: random.Random) -> tuple[str, str]:
    low = rng.randint(1, 18)
    side = rng.choice(("", "", "", "L", "R"))
    pair = (f"{low:02d}{side}", f"{low + 18:02d}{ ({'L': 'R', 'R': 'L'}.get(side, '')) }")
    return pair if rng.random() < 0.5 else pair[::-1]


def _displacement_sentence(rng: random.Random, runway: str, displacement: int, before_ft: int | None) -> str:
    cause = rng.choice(CAUSES)
    before = f" {before_ft}FT BFR THR {runway}" if before_ft else ""
    lateral = rng.choice(("", " ON EXTENDED RCL", f" AND {rng.randint(20, 400)}FT {rng.choice('NESW')} EXTENDED RCL"))
    if rng.random() < 0.2:
        increment = rng.randint(50, displacement - 50)
        return (
            f"THR {runway} FURTHER DISPLACED BY {increment}FT BEYOND PUBLISHED DTHR DUE {cause}{before}{lateral}. "
            f"(TOTAL DISPLACEMENT {displacement}FT)."
        )
    verb = rng.choice(("DISPLACED", "DISPLACED BY", "IS DISPLACED BY"))
    return f"THR {runway} {verb} {displacement}FT DUE {cause}{before}{lateral}."


def _declared_distances(rng, displaced, opposite, runway_ft, displacement, first_closed) -> dict[str, dict]:
    reduced = runway_ft - displacement
    take_off = reduced if first_closed else runway_ft

    def distances(tora: int, lda: int) -> dict:
        toda = tora + rng.choice((0, 0, rng.randint(100, 1200)))
        asda = rng.choice((tora, tora, runway_ft))
        return {"TORA": _ft(tora), "TODA": _ft(toda), "ASDA": _ft(asda), "LDA": _ft(lda)}

    return {displaced: distances(take_off, reduced), opposite: distances(reduced, rng.choice((reduced, take_off)))}


def _declared_lines(rng: random.Random, distances: dict[str, dict]) -> list[str]:
    pair = "/".join(sorted(distances))
    header = rng.choice(
        (
            f"WITH RWY {pair} SHORTENED, DECLARED DIST CHANGED TO:",
            f"DECLARED DIST WITH RWY {pair} LENGTH REDUCED:",
            "DECLARED DIST CHANGED TO:",
        )
    )
    colon = rng.choice(("", ":"))
    rows = [
        f"RWY {runway}{colon} " + " ".join(f"{name} {measure['value']}" for name, measure in distances[runway].items())
        for runway in sorted(distances)
    ]
    return [header, *rows]


def _effect(runway: str) -> dict:
    return {
        "runway": runway,
        "closure": "none",
        "closedLength": None,
        "closedEnd": None,
        "thresholdDisplacement": None,
        "declaredDistances": None,
        "surfaceCondition": None,
        "obstacle": None,
    }


def _obstacle(agl, msl, before_ft, runway) -> dict:
    return {
        "heightAGL": _ft(agl),
        "heightMSL": _ft(msl),
        "distance": _ft(before_ft) if before_ft else None,
        "distanceReference": f"THR {runway}" if before_ft else None,
        "bearingDegrees": None,
        "latitude": None,
        "longitude": None,
    }


def _ft(value: int) -> dict:
    return {"value": value, "unit": "ft"}
