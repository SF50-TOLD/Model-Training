#!/bin/bash
# Set up the Python environment for building the gold NOTAM evaluation set.
#
# Prerequisites:
#   - pyenv installed (brew install pyenv pyenv-virtualenv)
#
# Usage:
#   ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="notam-gold"
PYTHON_VERSION="3.14.5"

echo "============================================================"
echo "NOTAM Gold Evaluation Set - Environment Setup"
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
    # shellcheck disable=SC2016  # literal instructions for the user to copy into their shell config
    echo '  eval "$(pyenv init -)"'
    # shellcheck disable=SC2016  # literal instructions for the user to copy into their shell config
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
    read -rp "Install Python ${PYTHON_VERSION}? (y/n): " install_python
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
    read -rp "Recreate it? (y/n): " recreate
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

# Use it for this directory, and activate it for the rest of this script
pyenv local "${VENV_NAME}"
pyenv activate "${VENV_NAME}"

echo ""
echo "Upgrading pip..."
pip install --upgrade pip

echo ""
echo "Installing dependencies..."
pip install -r "${SCRIPT_DIR}/requirements.txt"

echo ""
echo "Installing the headless browsers for the review-site tests..."
python -m playwright install chromium webkit

# Create .env if it doesn't exist
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo ""
    echo "Creating .env from template..."
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
    echo "Edit ${SCRIPT_DIR}/.env with your API keys."
fi

mkdir -p "${SCRIPT_DIR}/data"

echo ""
echo "============================================================"
echo "Setup Complete!"
echo "============================================================"
echo ""
echo "Environment: ${VENV_NAME}"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Follow the pipeline in README.md, starting with ./download_notams.py"
echo ""
