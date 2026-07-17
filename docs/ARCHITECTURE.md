# Policy Gateway Architecture

This is the refined deployable architecture for the project. It keeps the original layer intent, but separates the runtime into practical production concerns: validated configuration, bounded API ingress, policy state management, durable settlement, upstream isolation, and operator controls.

```mermaid
flowchart TD
  Client[Client / Console / Automation]

  subgraph L5[Layer 5: Orchestration]
    Boot[FastAPI lifespan boot]
    Config[Pydantic Settings + optional config/*.json]
    Tasks[Flush / integrity / backup tasks]
    Signals[uvicorn signal handling]
  end

  subgraph L0[Layer 0: Host Governance]
    FDs[RLIMIT_NOFILE]
    OOM[optional oom_score_adj]
    Mem[/proc/meminfo MemAvailable]
  end

  subgraph L3[Layer 3: API + Security]
    Body[streaming body limit]
    Headers[security headers]
    Rate[per-client 120 RPM limiter]
    Routes[health ready ingest dispatch metrics admin]
  end

  subgraph L2[Layer 2: Policy Engine]
    Ring[EMA ring buffer]
    SPRT[SPRT-like score]
    Hyst[thresholds + hysteresis]
    State[NOMINAL THROTTLE DEGRADE FALLBACK ACCEPT_H0 PROMOTE]
  end

  subgraph L1[Layer 1: Durable Settlement]
    WAL[SQLite WAL + mmap]
    Sem[1 writer / 3 reader semaphores]
    Hash[SHA256 system_state]
    Backup[VACUUM INTO + manifest]
    Integrity[PRAGMA integrity_check]
  end

  subgraph L4[Layer 4: External Integration]
    HTTP[httpx AsyncClient]
    Circuit[Circuit breaker]
    Llama[llama.cpp-compatible endpoint]
    Fallback[standby fallback response]
  end

  subgraph OBS[Observability + Audit]
    Prom[Prometheus text metrics]
    Gate[200ms scrape gate]
    Audit[append-only SHA256 JSONL chain]
    Verify[audit verify + readiness]
  end

  Client --> Body --> Headers --> Rate --> Routes
  Config --> Boot --> Tasks
  Boot --> FDs & OOM
  Mem --> Hyst
  Routes --> Ring --> SPRT --> Hyst --> State
  State --> Sem --> WAL --> Hash --> Integrity --> Backup
  Routes --> HTTP --> Circuit
  Circuit -->|closed| Llama
  Circuit -->|open/fail| Fallback
  State --> Prom --> Gate
  Routes --> Audit --> Verify
  Integrity --> Verify
```

## Why this is more realistic

- **One production implementation, multiple layouts:** `policy_gateway` contains the real code; `src/layer_*` files are compatibility facades for teams that prefer diagram-aligned modules.
- **Fail-closed operations:** `/ready` requires database integrity and audit-chain validity; rollback verifies manifests before restoring.
- **Bounded ingress:** request size limits are enforced while streaming request bodies, not only through `Content-Length`.
- **Durable state:** metrics settlement uses SQLite WAL, a single writer semaphore, reader limits, checkpointing, integrity checks, and backup manifests.
- **Isolated upstream calls:** dispatches run through a timeout-bound async client and circuit breaker before fallback.
- **Buildable artifact:** Python package builds include the console assets and compatibility loader; Docker Compose gives a runnable stack.
