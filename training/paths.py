"""Filesystem locations for training the on-device NOTAM model."""

from notam_gold.paths import DATA_DIR, ROOT

TRAINING_DIR = ROOT / "training"
TRAINING_DATABASE = DATA_DIR / "notam_train.sqlite"
DATASET_DIR = DATA_DIR / "training"
