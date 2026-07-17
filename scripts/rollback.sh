#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${PGW_DATA_DIR:-var/policy-gateway}"
MANIFEST="${PGW_MANIFEST_PATH:-${DATA_DIR}/manifest.json}"
DB_PATH="${PGW_DATABASE_PATH:-${DATA_DIR}/gateway.db}"
AUDIT="${PGW_AUDIT_PATH:-${DATA_DIR}/audit.jsonl}"

if [[ ! -f "${MANIFEST}" ]]; then
  echo "ERROR: manifest not found: ${MANIFEST}" >&2
  exit 1
fi

python - <<'PY'
import hashlib, json, os, shutil, sqlite3, sys, time
from pathlib import Path

data_dir = Path(os.environ.get("PGW_DATA_DIR", "var/policy-gateway"))
manifest_path = Path(os.environ.get("PGW_MANIFEST_PATH", data_dir / "manifest.json"))
db_path = Path(os.environ.get("PGW_DATABASE_PATH", data_dir / "gateway.db"))
audit_path = Path(os.environ.get("PGW_AUDIT_PATH", data_dir / "audit.jsonl"))
manifest = json.loads(manifest_path.read_text())
source = Path(manifest["database"])
actual = hashlib.sha256(source.read_bytes()).hexdigest()
if actual != manifest["sha256"]:
    raise SystemExit("ERROR: backup SHA256 mismatch")
for suffix in ("-wal", "-shm"):
    Path(str(db_path) + suffix).unlink(missing_ok=True)
db_path.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(source, db_path)
with sqlite3.connect(db_path) as conn:
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
if ok != "ok":
    raise SystemExit(f"ERROR: integrity_check failed: {ok}")
audit_path.parent.mkdir(parents=True, exist_ok=True)
with audit_path.open("a", encoding="utf-8") as audit:
    audit.write(json.dumps({"ts": time.time(), "event": "rollback_script", "database": str(source), "sha256": actual}) + "\n")
print("Rollback complete; system can be restarted")
PY
