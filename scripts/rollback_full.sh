#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/rollback.sh"
"${SCRIPT_DIR}/healthcheck.sh" "${PGW_HEALTHCHECK_URL:-http://127.0.0.1:8000/ready}"
