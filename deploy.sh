#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-policy-gateway:latest}"
CONTAINER="${CONTAINER:-policy-gateway}"
PORT="${PORT:-8000}"
DATA_DIR="${PGW_DATA_DIR:-$(pwd)/var/policy-gateway}"

mkdir -p "${DATA_DIR}"
docker build -t "${IMAGE}" .
docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
docker run -d \
  --name "${CONTAINER}" \
  -p "${PORT}:8000" \
  -e PGW_DATA_DIR=/app/var/policy-gateway \
  -v "${DATA_DIR}:/app/var/policy-gateway" \
  "${IMAGE}"

scripts/healthcheck.sh "http://127.0.0.1:${PORT}/ready"
echo "deployed ${CONTAINER} from ${IMAGE} on port ${PORT}"
