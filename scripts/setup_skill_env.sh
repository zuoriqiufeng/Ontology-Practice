#!/usr/bin/env bash
#
# Setup a shared Python environment for Demo Product Manager Skills.
#
# Usage:
#   ./scripts/setup_skill_env.sh [REPO_ROOT]
#
# Default REPO_ROOT: $HOME/.demo-product/stream-agent
#
# This script will:
# 1. Ensure `uv` is available (installs if missing).
# 2. Create a Python 3.12 venv at $REPO_ROOT/.venv if it does not exist.
# 3. Install dependencies from $REPO_ROOT/skill/requirements.txt.

set -euo pipefail

REPO_ROOT="${1:-$HOME/.demo-product/stream-agent}"
REQUIREMENTS_FILE="$REPO_ROOT/skill/requirements.txt"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

echo "==> Setting up Manager Skill environment in: $REPO_ROOT"

if [ ! -d "$REPO_ROOT" ]; then
    echo "Creating repo root: $REPO_ROOT"
    mkdir -p "$REPO_ROOT"
fi

cd "$REPO_ROOT"

# Ensure uv is available
if ! command -v uv > /dev/null 2>&1; then
    echo "==> uv not found, installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Re-load PATH for the current shell session
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv > /dev/null 2>&1; then
    echo "ERROR: Failed to install uv or uv is not on PATH." >&2
    exit 1
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
    echo "==> Creating Python $PYTHON_VERSION venv at $REPO_ROOT/.venv"
    uv venv --python "$PYTHON_VERSION"
else
    echo "==> Existing venv found at $REPO_ROOT/.venv"
fi

# Install / upgrade dependencies
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "==> Installing dependencies from $REQUIREMENTS_FILE"
    uv pip install -r "$REQUIREMENTS_FILE"
else
    echo "WARNING: Requirements file not found: $REQUIREMENTS_FILE" >&2
    echo "Skipping dependency installation." >&2
fi

echo "==> Manager Skill environment ready."
echo "    Python: $REPO_ROOT/.venv/bin/python"
echo "    Use with: cd $REPO_ROOT && .venv/bin/python skill/<skill>/scripts/<script>.py ..."
