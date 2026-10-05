"""The fields a converted model may propose to the pilot, recorded in its `notam-model.json`.

The app proposes a model-read field only when the model's manifest lists it, so a model proposes
nothing until its held-out gate run shows which fields it reads safely. Obstacle distance, reference
and direction are never proposed, so they can't be listed.
"""

import argparse

PROPOSABLE_FIELDS = (
    "closure",
    "partialClosure",
    "thresholdDisplacement",
    "TORA",
    "LDA",
    "rwyCC",
    "contaminants",
    "obstacleHeight",
)


def proposable_fields(text: str) -> list[str]:
    """The comma-separated field names in ``text``, in schema order; raises on an unknown name."""
    names = {name.strip() for name in text.split(",") if name.strip()}
    if unknown := names - set(PROPOSABLE_FIELDS):
        raise argparse.ArgumentTypeError(f"not proposable: {', '.join(sorted(unknown))}")
    return [field for field in PROPOSABLE_FIELDS if field in names]
