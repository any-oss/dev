#!/bin/bash
set -euo pipefail
PREVIOUS_TAG="${1:-}"
IMAGE="anydockerhub/dev"
if [[ -z "$PREVIOUS_TAG" ]]; then
    echo "ERROR: Previous tag required. Usage: $0 <tag>"
    exit 1
fi
docker manifest inspect "${IMAGE}:${PREVIOUS_TAG}" > /dev/null 2>&1 || {
    echo "ERROR: Image not found"
    exit 1
}
docker pull "${IMAGE}:${PREVIOUS_TAG}"
docker tag "${IMAGE}:${PREVIOUS_TAG}" "${IMAGE}:latest"
docker push "${IMAGE}:latest"
echo "Rollback complete: ${IMAGE}:latest -> ${PREVIOUS_TAG}"
