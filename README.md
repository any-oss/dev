# Policy Gateway

A production-oriented FastAPI service generated from the supplied Mermaid architecture diagrams. It models all major layers: orchestration, infrastructure governance, API validation/rate limiting, EMA/SPRT policy logic, SQLite WAL settlement, httpx dispatch with circuit breaking, metrics, audit chaining, backup, and rollback.

## Architecture Mapping

| Diagram layer | Implementation |
| --- | --- |
| Layer 5 Orchestration & Lifecycle | FastAPI lifespan dependency injection, validated `Settings`, graceful `uvicorn` shutdown hooks. |
| Layer 0 Infrastructure & Resource Governance | file descriptor limit enforcement, optional `oom_score_adj`, `/proc/meminfo` memory bounds. |
| Layer 3 API Gateway & Security | `/api/v1/ingest`, `/api/v1/dispatch`, Pydantic schemas, 120 RPM rate limiter. |
| Layer 2 Policy & Aggregation Engine | EMA ring buffer, p95/error/QPS metrics, SPRT-like log likelihood, hysteresis state machine. |
| Layer 1 Data & Settlement | SQLite WAL mode, one-writer/three-reader semaphores, `traffic_metrics`, `system_state`, checkpoints, backups. |
| Layer 4 External Dispatch | pooled `httpx.AsyncClient`, timeout control, circuit breaker, standby fallback response. |
| Observability & Audit | Prometheus text metrics, 200ms scrape gate, append-only SHA256 JSONL audit chain with continuity verification. |
| Full-stack Console | Packaged static HTML/CSS/JS dashboard served from `/` and `/static/*`. |
| Rollback | manifest restore, SHA256 validation, integrity check, audit logging. |

## Runtime Requirements

- Python 3.11+
- Linux recommended for `/proc/meminfo` and `oom_score_adj`; the service still runs on non-Linux hosts with safe fallbacks.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

## Run

```bash
uvicorn policy_gateway.main:app --host 0.0.0.0 --port 8000
```

Or install the package and use the console entry point:

```bash
pip install -e .
policy-gateway
```

## Configuration

All settings are environment-driven with the `PGW_` prefix.

| Variable | Default | Purpose |
| --- | --- | --- |
| `PGW_RATE_LIMIT_RPM` | `120` | Per-client ingest limit. |
| `PGW_METRICS_SCRAPE_GATE_MS` | `200` | Minimum interval between successful `/metrics` scrapes. |
| `PGW_FLUSH_INTERVAL_S` | `25` | Background SQLite metrics flush and ring-buffer reset interval. |
| `PGW_INTEGRITY_INTERVAL_S` | `60` | SQLite `PRAGMA integrity_check` cadence. |
| `PGW_BACKUP_INTERVAL_S` | `900` | `VACUUM INTO` snapshot cadence. |
| `PGW_MEMORY_FLOOR_KB` | `950000` | Memory floor that triggers throttle policy. |
| `PGW_QPS_HIGH` / `PGW_QPS_LOW` | `320` / `280` | Throttle enter/exit hysteresis. |
| `PGW_P95_LATENCY_MS` | `1850` | Degrade policy threshold. |
| `PGW_ERROR_RATE_HIGH` | `0.045` | Fallback policy threshold. |
| `PGW_UPSTREAM_URL` | `http://127.0.0.1:8080/completion` | llama.cpp-compatible upstream endpoint. |
| `PGW_DATA_DIR` | `var/policy-gateway` | Database, manifest, audit, and backup root. |
| `PGW_AUDIT_MAX_BYTES` | `10485760` | Audit JSONL rotation size. |


## Team-B Layout Compatibility

This repository keeps the production package in `src/policy_gateway/`, and also provides the Team-B-style layer map for operators that expect split layer files:

```text
config/                    # JSON defaults for layers 0-4 plus security
src/config_loader.py        # Loads/validates layer JSON into Settings
src/layer_0/resource.py     # Resource governance facade
src/layer_1/data.py         # SQLite WAL data facade
src/layer_2/logic.py        # EMA/SPRT policy facade
src/layer_3/api.py          # FastAPI app facade
src/layer_4/dispatch.py     # httpx/circuit-breaker facade
src/layer_5/                # Orchestrator and backup facades
src/observability/exporter.py
scripts/provision.sh
scripts/rollback_full.sh
scripts/healthcheck.sh
deploy.sh
```

The facades are intentionally thin wrappers around `policy_gateway` so there is one production implementation and one compatibility layout.

## Full-Stack Console

Open the bundled dashboard after startup:

```bash
open http://localhost:8000/
```

The UI is packaged into the Python wheel, served by FastAPI, and provides live health/metrics display plus forms for ingest and dispatch probes.

## API

### Ingest

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H 'Content-Type: application/json' \
  -d '{"latency_ms":42,"status_code":200}'
```

Returns `202 Accepted` with `{ "status": "queued", "ts": ... }` after Pydantic validation, rate limiting, EMA update, and audit append.

### Dispatch

```bash
curl -X POST http://localhost:8000/api/v1/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"prompt":"hello"},"mem_kb":2000000}'
```

Resolves the current policy state and routes to the upstream or fallback path. `DEGRADE` injects a `context_limit` of `1024` and requests KV-cache clearing; `FALLBACK` and `THROTTLE` use standby cache routing.

### Metrics

```bash
curl http://localhost:8000/metrics
```

Exposes Prometheus text metrics and rejects scrapes inside the configured gate interval with `429`.

### Readiness and Audit Verification

```bash
curl http://localhost:8000/ready
curl http://localhost:8000/admin/audit/verify
```

`/ready` verifies SQLite integrity and audit chain health before reporting the service ready. `/admin/audit/verify` walks the JSONL hash chain and fails closed on previous-hash or line-hash mismatches.

### Rollback

```bash
curl -X POST http://localhost:8000/admin/rollback
```

Restores the latest manifest-backed SQLite snapshot, verifies SHA256, runs `PRAGMA integrity_check`, and returns the system to online status or fails closed.

## Tests and Build

```bash
pytest -q
python -m compileall -q src
python -m build
```

A convenience `Makefile` is also provided:

```bash
make install
make test
make build
```

## Deployment

Build the production container:

```bash
docker build -t policy-gateway:latest .
```

Run it:

```bash
docker run --rm -p 8000:8000 -e PGW_UPSTREAM_URL=http://llama:8080/completion policy-gateway:latest
```
