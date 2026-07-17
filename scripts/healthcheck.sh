#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://127.0.0.1:8000/ready}"
python - "$URL" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as response:
    payload = json.loads(response.read().decode())
    if response.status != 200 or payload.get("status") not in {"ready", "ok"}:
        raise SystemExit(f"unhealthy response: {response.status} {payload}")
print(f"healthy: {url}")
PY
