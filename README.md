# NOTAM Adapter Training

Train a Foundation Models LoRA adapter to extract structured runway performance data from raw NOTAM text.

## Quick Start

```bash
# 1. Setup environment
./setup.sh

# 2. Prepare training data
./prepare_data.sh

# 3. Train the adapter
./train_adapter.sh

# 4. Upload to App Store Connect
./upload_adapter.sh
```

## Overview

This pipeline trains a custom LoRA adapter for Apple's Foundation Models framework to parse NOTAMs and extract runway performance data.

```
[NOTAM API] → [Filter] → [Label with Claude] → [Train] → [Export] → [Upload]
```

## Prerequisites

- macOS with Apple Silicon (32GB+ RAM recommended)
- Python 3.11 (via pyenv)
- [Apple's adapter training toolkit](https://developer.apple.com/apple-intelligence/foundation-models-adapter/)
- Anthropic API key (for labeling)
- Apple Developer Program membership (for hosting)

## Setup

### 1. Install Apple's Toolkit

Download from [Apple Developer](https://developer.apple.com/apple-intelligence/foundation-models-adapter/):

```bash
unzip adapter_training_toolkit_v26_0_0.zip
```

### 2. Setup Python Environment

```bash
./setup.sh
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required variables:
- `ANTHROPIC_API_KEY` - For Claude-based labeling
- `TOOLKIT_PATH` - Path to Apple's toolkit
- `ASC_ISSUER_ID`, `ASC_KEY_ID`, `ASC_PRIVATE_KEY_PATH` - App Store Connect API credentials
- `APP_APPLE_ID` - Your app's Apple ID (numeric)

## Data Preparation

```bash
./prepare_data.sh
```

Or run individual steps:

1. `python download_all_notams.py` - Download NOTAMs from API
2. `python filter_relevant_notams.py` - Filter runway-relevant NOTAMs
3. `python generate_silver_labels.py` - Label with Claude
4. `python review_tool.py --low-confidence` - Review low-confidence labels
5. `python fix_silver_labels.py` - Apply automatic fixes
6. `python format_training_data.py` - Format for training

## Training

```bash
./train_adapter.sh
```

Options:
- `--export-only` - Export existing checkpoint without training

Environment variables:
| Variable | Default | Description |
|----------|---------|-------------|
| `TOOLKIT_PATH` | required | Apple toolkit location |
| `EPOCHS` | 5 | Training epochs |
| `BATCH_SIZE` | 4 | Batch size (reduce if OOM) |
| `LEARNING_RATE` | 1e-3 | Learning rate |

For memory issues:
```bash
BATCH_SIZE=1 ./train_adapter.sh
```

## Upload

```bash
./upload_adapter.sh
```

Options:
- `--dry-run` - Validate without uploading

The script uses the App Store Connect API to:
1. Create/find an asset pack
2. Create a new version
3. Upload the adapter
4. Commit and verify processing

### Required Entitlement

Request the **Foundation Models Framework Adapter Entitlement** from Apple before shipping:
1. Go to [Apple Developer Account](https://developer.apple.com/account)
2. Certificates, Identifiers & Profiles → Identifiers
3. Select your App ID → Request entitlement

## Directory Structure

```
├── setup.sh               # Environment setup
├── prepare_data.sh        # Data preparation pipeline
├── train_adapter.sh       # Training script
├── upload_adapter.sh      # Upload to App Store Connect
├── requirements.txt       # Python dependencies
├── .env.example           # Environment template
├── data/                  # Training data (gitignored)
├── checkpoints/           # Model checkpoints (gitignored)
└── exports/               # Exported adapters (gitignored)
```

## Data Schema

### Training Format

```json
[
  {"role": "user", "content": "Extract runway data from this NOTAM...\n\nRWY 28L THR DSPLCD 500FT"},
  {"role": "assistant", "content": "{\"airportID\":\"KSFO\",\"runway\":\"28L\",\"takeoffShortening\":500,...}"}
]
```

### Extraction Fields

| Field | Type | Description |
|-------|------|-------------|
| `airportID` | string | ICAO airport code |
| `runway` | string? | Runway designator |
| `runwayClosed` | bool | Runway fully closed |
| `takeoffShortening` | number? | Takeoff distance reduction |
| `landingShortening` | number? | Landing distance reduction |
| `TORA`, `TODA`, `LDA` | number? | Declared distances |
| `obstacleHeight` | number? | Obstacle height AGL |
| `contaminations` | array | Surface contaminations |

## References

- [Foundation Models adapter training](https://developer.apple.com/apple-intelligence/foundation-models-adapter/)
- [Background Assets framework](https://developer.apple.com/documentation/backgroundassets)
- [App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi)

## License

MIT License - see [LICENSE](LICENSE)
