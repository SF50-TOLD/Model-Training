#!/bin/bash
# Prepare training data for NOTAM adapter
#
# This script runs the complete data preparation pipeline:
# 1. Download NOTAMs from API
# 2. Filter to runway-relevant NOTAMs
# 3. Generate silver labels with Claude
# 4. Fix systemic labeling issues
# 5. Format for training
#
# Prerequisites:
#   - ./setup.sh has been run
#   - .env file configured with API keys
#
# Usage:
#   ./prepare_data.sh              # Run full pipeline
#   ./prepare_data.sh --skip-download  # Skip download (use existing data)
#   ./prepare_data.sh --skip-labeling  # Skip Claude labeling

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse arguments
SKIP_DOWNLOAD=false
SKIP_LABELING=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-download)
            SKIP_DOWNLOAD=true
            shift
            ;;
        --skip-labeling)
            SKIP_LABELING=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-download   Skip downloading NOTAMs (use existing data/all_notams.json)"
            echo "  --skip-labeling   Skip Claude labeling (use existing data/silver_dataset.jsonl)"
            echo "  --help, -h        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================================"
echo "NOTAM Adapter Training - Data Preparation"
echo "============================================================"
echo ""

# Activate pyenv environment
echo "Activating Python environment..."
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)" 2>/dev/null || true
pyenv activate adapter-training

# Check for .env
if [ ! -f ".env" ]; then
    echo "Error: .env file not found"
    echo "Run: cp .env.example .env"
    echo "Then edit .env with your API keys."
    exit 1
fi

# Load environment variables
set -a
source .env
set +a

# Step 1: Download NOTAMs
echo ""
echo "============================================================"
echo "Step 1: Download NOTAMs"
echo "============================================================"

if [ "$SKIP_DOWNLOAD" = true ]; then
    echo "Skipping download (--skip-download)"
    if [ ! -f "data/all_notams.json" ]; then
        echo "Error: data/all_notams.json not found"
        exit 1
    fi
else
    if [ -z "$NOTAM_API_TOKEN" ]; then
        echo "Error: NOTAM_API_TOKEN not set in .env"
        exit 1
    fi
    python download_all_notams.py
fi

# Step 2: Filter relevant NOTAMs
echo ""
echo "============================================================"
echo "Step 2: Filter Relevant NOTAMs"
echo "============================================================"
python filter_relevant_notams.py

# Step 3: Generate silver labels
echo ""
echo "============================================================"
echo "Step 3: Generate Silver Labels with Claude"
echo "============================================================"

if [ "$SKIP_LABELING" = true ]; then
    echo "Skipping labeling (--skip-labeling)"
    if [ ! -f "data/silver_dataset.jsonl" ]; then
        echo "Error: data/silver_dataset.jsonl not found"
        exit 1
    fi
else
    if [ -z "$ANTHROPIC_API_KEY" ]; then
        echo "Error: ANTHROPIC_API_KEY not set in .env"
        exit 1
    fi
    python generate_silver_labels.py
fi

# Step 4: Fix systemic issues
echo ""
echo "============================================================"
echo "Step 4: Fix Systemic Labeling Issues"
echo "============================================================"
python fix_silver_labels.py

# Step 5: Format for training
echo ""
echo "============================================================"
echo "Step 5: Format Training Data"
echo "============================================================"
python format_training_data.py

# Summary
echo ""
echo "============================================================"
echo "Data Preparation Complete!"
echo "============================================================"
echo ""

# Count files
if [ -f "data/train.jsonl" ]; then
    TRAIN_COUNT=$(wc -l < "data/train.jsonl" | tr -d ' ')
    VALID_COUNT=$(wc -l < "data/valid.jsonl" | tr -d ' ')
    TEST_COUNT=$(wc -l < "data/test.jsonl" | tr -d ' ')

    echo "Training data ready:"
    echo "  Train: $TRAIN_COUNT examples"
    echo "  Valid: $VALID_COUNT examples"
    echo "  Test:  $TEST_COUNT examples"
    echo ""
fi

if [ -f "data/low_confidence.jsonl" ]; then
    LOW_CONF_COUNT=$(wc -l < "data/low_confidence.jsonl" | tr -d ' ')
    if [ "$LOW_CONF_COUNT" -gt 0 ]; then
        echo "Note: $LOW_CONF_COUNT low-confidence items may need review."
        echo "Run: python review_tool.py --low-confidence"
        echo ""
    fi
fi

echo "Next step: ./train_adapter.sh"
echo ""
