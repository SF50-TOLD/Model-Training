#!/bin/bash
# Train and export a Foundation Models adapter using Apple's toolkit
#
# Prerequisites:
#   - Mac with Apple Silicon (32GB+ RAM recommended)
#   - Python 3.11 environment with toolkit dependencies
#   - Apple's adapter_training_toolkit
#
# Usage:
#   ./train_adapter.sh                    # Train and export
#   ./train_adapter.sh --export-only      # Export existing checkpoint
#   BATCH_SIZE=1 ./train_adapter.sh       # Reduce batch size for OOM

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".env" ]; then
    set -a && source .env && set +a
fi

# Configuration
TOOLKIT_PATH="${TOOLKIT_PATH:-}"
TRAINING_DATA="${TRAINING_DATA:-data/train.jsonl}"
EVAL_DATA="${EVAL_DATA:-data/valid.jsonl}"
CHECKPOINT_DIR="${CHECKPOINT_DIR:-checkpoints}"
OUTPUT_DIR="${OUTPUT_DIR:-exports}"
ADAPTER_NAME="${ADAPTER_NAME:-NOTAMAdapter}"

# Hyperparameters
EPOCHS="${EPOCHS:-5}"
LEARNING_RATE="${LEARNING_RATE:-1e-3}"
BATCH_SIZE="${BATCH_SIZE:-4}"
GRADIENT_ACCUMULATION="${GRADIENT_ACCUMULATION:-1}"

# Parse arguments
EXPORT_ONLY=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --export-only) EXPORT_ONLY=true; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --export-only   Export from existing checkpoint"
            echo "  --help, -h      Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  TOOLKIT_PATH          Path to Apple's toolkit"
            echo "  EPOCHS                Training epochs (default: 5)"
            echo "  LEARNING_RATE         Learning rate (default: 1e-3)"
            echo "  BATCH_SIZE            Batch size (default: 4)"
            echo "  GRADIENT_ACCUMULATION Gradient accumulation steps (default: 1)"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "============================================================"
echo "Adapter Training"
echo "============================================================"
echo ""

# Validate toolkit
[ -n "$TOOLKIT_PATH" ] || { echo "Error: TOOLKIT_PATH not set"; exit 1; }
[ -d "$TOOLKIT_PATH" ] || { echo "Error: Toolkit not found at $TOOLKIT_PATH"; exit 1; }

# Validate training data
if [ "$EXPORT_ONLY" = false ] && [ ! -f "$TRAINING_DATA" ]; then
    echo "Error: Training data not found at $TRAINING_DATA"
    exit 1
fi

mkdir -p "$CHECKPOINT_DIR" "$OUTPUT_DIR"

# Setup Python environment
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)" 2>/dev/null || true
pyenv activate adapter-training-311 2>/dev/null || pyenv activate adapter-training

export PYTHONPATH="$TOOLKIT_PATH:$PYTHONPATH"

echo "Toolkit:     $TOOLKIT_PATH"
echo "Epochs:      $EPOCHS"
echo "Batch size:  $BATCH_SIZE"
if [ -f "$TRAINING_DATA" ]; then
    echo "Training:    $(wc -l < "$TRAINING_DATA" | tr -d ' ') examples"
fi
echo ""

# Train
if [ "$EXPORT_ONLY" = false ]; then
    echo "Training..."
    python -m examples.train_adapter \
        --train-data "$TRAINING_DATA" \
        --eval-data "$EVAL_DATA" \
        --epochs "$EPOCHS" \
        --learning-rate "$LEARNING_RATE" \
        --batch-size "$BATCH_SIZE" \
        --gradient-accumulation-steps "$GRADIENT_ACCUMULATION" \
        --checkpoint-dir "$CHECKPOINT_DIR"
fi

# Export
echo ""
echo "Exporting..."
CHECKPOINT=$(ls -t "$CHECKPOINT_DIR"/*.pt 2>/dev/null | head -1)
[ -n "$CHECKPOINT" ] || { echo "Error: No checkpoint found"; exit 1; }

python -m export.export_fmadapter \
    --adapter-name "$ADAPTER_NAME" \
    --checkpoint "$CHECKPOINT" \
    --output-dir "$OUTPUT_DIR"

ADAPTER_PATH="$OUTPUT_DIR/$ADAPTER_NAME.fmadapter"
echo ""
echo "============================================================"
echo "Complete!"
echo "============================================================"
echo ""
echo "Adapter: $ADAPTER_PATH"
[ -d "$ADAPTER_PATH" ] && echo "Size:    $(du -sh "$ADAPTER_PATH" | cut -f1)"
echo ""
echo "Next: ./upload_adapter.sh"
