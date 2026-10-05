"""Builders for NOTAMExtraction values with every key present."""


def length(value, unit="ft"):
    return {"value": value, "unit": unit}


def height(value, unit="ft", datum="AGL"):
    return {"value": value, "unit": unit, "datum": datum}


def effect(runway="09", closure="none", **fields):
    return {
        "runway": runway,
        "closure": closure,
        "partialClosure": None,
        "thresholdDisplacement": None,
        "declaredDistances": None,
        "surfaceCondition": None,
    } | fields


def partial(length=None, end=None):  # noqa: A002
    return {"length": length, "end": end}


def declared(TORA=None, LDA=None):  # noqa: N803
    return {"TORA": TORA, "LDA": LDA}


def contaminant(type="wet", coveragePercent=None, depth=None):  # noqa: A002, N803
    return {"type": type, "coveragePercent": coveragePercent, "depth": depth}


def surface(rwyCC=None, contaminants=()):  # noqa: N803
    return {"rwyCC": rwyCC, "contaminants": list(contaminants)}


def reference(kind="ARP", runway=None):
    return {"kind": kind, "runway": runway}


def obstacle(height=None, distance=None, reference=None, direction=None):  # noqa: A002
    return {"height": height, "distance": distance, "reference": reference, "direction": direction}


def extraction(*effects, obstacles=(), isCanceled=False):  # noqa: N803
    return {"isCanceled": isCanceled, "effects": list(effects), "obstacles": list(obstacles)}
