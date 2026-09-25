"""Builders for NOTAMExtraction values with every key present."""


def length(value, unit="ft"):
    return {"value": value, "unit": unit}


def effect(runway="09", closure="none", **fields):
    return {
        "runway": runway,
        "closure": closure,
        "closedLength": None,
        "closedEnd": None,
        "thresholdDisplacement": None,
        "declaredDistances": None,
        "surfaceCondition": None,
        "obstacle": None,
    } | fields


def declared(TORA=None, TODA=None, ASDA=None, LDA=None):  # noqa: N803
    return {"TORA": TORA, "TODA": TODA, "ASDA": ASDA, "LDA": LDA}


def contaminant(type="wet", runwayThird=None, coveragePercent=None, depth=None):  # noqa: A002, N803
    return {"type": type, "runwayThird": runwayThird, "coveragePercent": coveragePercent, "depth": depth}


def surface(rwyCC=None, contaminants=()):  # noqa: N803
    return {"rwyCC": rwyCC, "contaminants": list(contaminants)}


def obstacle(**fields):
    return {
        "heightAGL": None,
        "heightMSL": None,
        "distance": None,
        "distanceReference": None,
        "bearingDegrees": None,
        "latitude": None,
        "longitude": None,
    } | fields


def extraction(*effects, isCanceled=False):  # noqa: N803
    return {"isCanceled": isCanceled, "effects": list(effects)}
