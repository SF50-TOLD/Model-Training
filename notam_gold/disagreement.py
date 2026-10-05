"""Field-level disagreement between two silver extractions of the same NOTAM."""

from dataclasses import dataclass

from notam_gold.schema import canonicalize

# Safety-critical fields: a disagreement under one of these doubles the review priority.
HEAVY_FIELDS = ("closure", "partialClosure", "partialClosure.length", "thresholdDisplacement", "declaredDistances")


@dataclass(frozen=True)
class Difference:
    """One disagreeing path, indexed like extraction A (``effects[B:j]`` for items only B has)."""

    path: str
    a: object
    b: object

    def to_dict(self) -> dict:
        return {"path": self.path, "a": self.a, "b": self.b}


def _align(items_a: list[dict], items_b: list[dict], key) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Pair items with the same ``key``, each at most once, in order."""
    unmatched_b = list(range(len(items_b)))
    pairs, only_a = [], []
    for i, item in enumerate(items_a):
        match = next((j for j in unmatched_b if key(items_b[j]) == key(item)), None)
        if match is None:
            only_a.append(i)
        else:
            pairs.append((i, match))
            unmatched_b.remove(match)
    return pairs, only_a, unmatched_b


def _runway(effect: dict):
    return effect["runway"]


def _referenced_runway(obstacle: dict):
    return (obstacle["reference"] or {}).get("runway")


def _compare(a, b, path: str):
    """Yield differences, descending only while both sides are objects; lists compare whole."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a.keys() | b.keys():
            yield from _compare(a.get(key), b.get(key), f"{path}.{key}")
    elif a != b:
        yield Difference(path, a, b)


def _section(a: dict, b: dict, name: str, key) -> list[Difference]:
    pairs, only_a, only_b = _align(a[name], b[name], key)
    differences = []
    for i, j in pairs:
        differences += _compare(a[name][i], b[name][j], f"{name}[{i}]")
    differences += [Difference(f"{name}[{i}]", a[name][i], None) for i in only_a]
    differences += [Difference(f"{name}[B:{j}]", None, b[name][j]) for j in only_b]
    return differences


def diff(a: dict, b: dict) -> list[Difference]:
    """Every path at which extractions ``a`` and ``b`` disagree."""
    a, b = canonicalize(a), canonicalize(b)
    differences = []
    if a["isCanceled"] != b["isCanceled"]:
        differences.append(Difference("isCanceled", a["isCanceled"], b["isCanceled"]))
    differences += _section(a, b, "effects", _runway)
    differences += _section(a, b, "obstacles", _referenced_runway)
    return sorted(differences, key=lambda d: d.path)


def _is_heavy(difference: Difference) -> bool:
    if "." not in difference.path:
        return True
    field = difference.path.split("].", 1)[1]
    return any(field == heavy or field.startswith(f"{heavy}.") and heavy != "partialClosure" for heavy in HEAVY_FIELDS)


def score(differences: list[Difference]) -> int:
    """Review priority: disagreements on whole effects and safety-critical fields count double."""
    return sum(2 if _is_heavy(d) else 1 for d in differences) + sum(d.path == "isCanceled" for d in differences)
