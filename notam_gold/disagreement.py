"""Field-level disagreement between two silver extractions of the same NOTAM."""

from dataclasses import dataclass

from notam_gold.schema import canonicalize

HEAVY_FIELDS = ("isCanceled", "closure", "closedLength", "thresholdDisplacement", "declaredDistances")


@dataclass(frozen=True)
class Difference:
    """One disagreeing path, indexed like extraction A (``effects[B:j]`` for effects only B has)."""

    path: str
    a: object
    b: object

    def to_dict(self) -> dict:
        return {"path": self.path, "a": self.a, "b": self.b}


def _align(effects_a: list[dict], effects_b: list[dict]) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Pair effects by runway designator (preferring equal closure), then by order."""
    unmatched_b = list(range(len(effects_b)))
    pairs, only_a = [], []
    for i, effect in enumerate(effects_a):
        same_runway = [j for j in unmatched_b if effects_b[j]["runway"] == effect["runway"]]
        same_closure = [j for j in same_runway if effects_b[j]["closure"] == effect["closure"]]
        match = (same_closure or same_runway or [None])[0]
        if match is None:
            only_a.append(i)
        else:
            pairs.append((i, match))
            unmatched_b.remove(match)
    return pairs, only_a, unmatched_b


def _compare(a, b, path: str):
    """Yield differences, descending only while both sides are objects; lists compare whole."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a.keys() | b.keys():
            yield from _compare(a.get(key), b.get(key), f"{path}.{key}")
    elif a != b:
        yield Difference(path, a, b)


def _canonical_contaminants(effect: dict) -> dict:
    return canonicalize({"isCanceled": False, "effects": [effect]})["effects"][0]


def diff(a: dict, b: dict) -> list[Difference]:
    """Every path at which extractions ``a`` and ``b`` disagree."""
    differences = []
    if a["isCanceled"] != b["isCanceled"]:
        differences.append(Difference("isCanceled", a["isCanceled"], b["isCanceled"]))
    pairs, only_a, only_b = _align(a["effects"], b["effects"])
    for i, j in pairs:
        left, right = (_canonical_contaminants(x["effects"][k]) for x, k in ((a, i), (b, j)))
        differences += _compare(left, right, f"effects[{i}]")
    differences += [Difference(f"effects[{i}]", a["effects"][i], None) for i in only_a]
    differences += [Difference(f"effects[B:{j}]", None, b["effects"][j]) for j in only_b]
    return sorted(differences, key=lambda d: d.path)


def _is_heavy(difference: Difference) -> bool:
    whole_effect = "." not in difference.path and difference.path != "isCanceled"
    return whole_effect or any(field in difference.path for field in HEAVY_FIELDS)


def score(differences: list[Difference]) -> int:
    """Review priority: disagreements on whole effects and safety-critical fields count double."""
    return sum(2 if _is_heavy(d) else 1 for d in differences) + sum(d.path == "isCanceled" for d in differences)
