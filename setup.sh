#!/bin/bash
# Setup Python environment for NOTAM adapter training
#
# Prerequisites:
#   - pyenv installed (brew install pyenv pyenv-virtualenv)
#   - Apple's adapter_training_toolkit downloaded
#
# Usage:
#   ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="adapter-training"
PYTHON_VERSION="3.13.7"
TOOLKIT_PATH="${TOOLKIT_PATH:-./adapter_training_toolkit_v26_0_0}"

echo "============================================================"
echo "NOTAM Adapter Training - Environment Setup"
echo "============================================================"
echo ""

# Check for pyenv
if ! command -v pyenv &> /dev/null; then
    echo "Error: pyenv is not installed"
    echo ""
    echo "Install with:"
    echo "  brew install pyenv pyenv-virtualenv"
    echo ""
    echo "Then add to your shell config:"
    echo '  eval "$(pyenv init -)"'
    echo '  eval "$(pyenv virtualenv-init -)"'
    exit 1
fi

# Initialize pyenv
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)" 2>/dev/null || true

# Check if Python version is installed
if ! pyenv versions --bare | grep -q "^${PYTHON_VERSION}$"; then
    echo "Python ${PYTHON_VERSION} not installed."
    echo ""
    read -p "Install Python ${PYTHON_VERSION}? (y/n): " install_python
    if [[ "$install_python" == "y" ]]; then
        echo "Installing Python ${PYTHON_VERSION}..."
        pyenv install "${PYTHON_VERSION}"
    else
        echo "Please install Python ${PYTHON_VERSION} or modify PYTHON_VERSION in this script."
        exit 1
    fi
fi

# Check if virtualenv exists
if pyenv versions --bare | grep -q "^${VENV_NAME}$"; then
    echo "Virtualenv '${VENV_NAME}' already exists."
    read -p "Recreate it? (y/n): " recreate
    if [[ "$recreate" == "y" ]]; then
        echo "Removing existing virtualenv..."
        pyenv virtualenv-delete -f "${VENV_NAME}"
    else
        echo "Using existing virtualenv."
    fi
fi

# Create virtualenv if it doesn't exist
if ! pyenv versions --bare | grep -q "^${VENV_NAME}$"; then
    echo "Creating virtualenv '${VENV_NAME}'..."
    pyenv virtualenv "${PYTHON_VERSION}" "${VENV_NAME}"
fi

# Activate virtualenv
echo "Activating ${VENV_NAME}..."
pyenv activate "${VENV_NAME}"

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip

# Install data preparation dependencies
echo ""
echo "Installing data preparation dependencies..."
pip install -r "${SCRIPT_DIR}/requirements.txt"

# Check for Apple toolkit
echo ""
if [ -d "$TOOLKIT_PATH" ]; then
    echo "Found Apple toolkit at: $TOOLKIT_PATH"

    # Install toolkit dependencies
    if [ -f "$TOOLKIT_PATH/requirements.txt" ]; then
        echo "Installing toolkit dependencies..."
        pip install -r "$TOOLKIT_PATH/requirements.txt"
    else
        echo "Warning: No requirements.txt found in toolkit"
    fi
else
    echo "Warning: Apple toolkit not found at $TOOLKIT_PATH"
    echo ""
    echo "Download from: https://developer.apple.com/apple-intelligence/foundation-models-adapter/"
    echo "Then either:"
    echo "  - Extract to ./adapter_training_toolkit_v26_0_0"
    echo "  - Or set TOOLKIT_PATH in .env"
fi

# Create .env if it doesn't exist
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo ""
    echo "Creating .env from template..."
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
    echo "Edit ${SCRIPT_DIR}/.env with your API keys."
fi

# Create data directories
echo ""
echo "Creating directories..."
mkdir -p "${SCRIPT_DIR}/data"
mkdir -p "${SCRIPT_DIR}/checkpoints"
mkdir -p "${SCRIPT_DIR}/exports"

echo ""
echo "============================================================"
echo "Setup Complete!"
echo "============================================================"
echo ""
echo "Environment: ${VENV_NAME}"
echo ""
echo "To activate manually:"
echo "  pyenv activate ${VENV_NAME}"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run ./prepare_data.sh to prepare training data"
echo "  3. Run ./train_adapter.sh to train the adapter"
echo ""
