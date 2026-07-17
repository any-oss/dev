#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python3}"
VENV="${VENV:-.venv}"
DATA_DIR="${PGW_DATA_DIR:-var/policy-gateway}"

"${PYTHON_BIN}" -m venv "${VENV}"
"${VENV}/bin/pip" install --upgrade pip
"${VENV}/bin/pip" install -r requirements-dev.txt
"${VENV}/bin/pip" install -e .
mkdir -p "${DATA_DIR}/backups"
"${VENV}/bin/python" -m compileall -q src

echo "Provisioned policy-gateway in ${VENV}; data dir: ${DATA_DIR}"
