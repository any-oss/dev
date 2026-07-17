from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path

from .audit import AuditChain
from .config import Settings
from .models import MetricsSnapshot


class DataStore:
    """Layer 1: SQLite WAL pool with 1-writer/3-reader semaphores and settlement."""

    def __init__(self, settings: Settings, audit: AuditChain) -> None:
        self.settings = settings
        self.audit = audit
        self.db_path = settings.database_path
        assert self.db_path is not None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = asyncio.Semaphore(1)
        self.readers = asyncio.Semaphore(3)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=self.settings.query_timeout_ms / 1000, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA mmap_size=67108864")
        conn.execute(f"PRAGMA busy_timeout={int(self.settings.query_timeout_ms)}")
        return conn

    async def initialize(self) -> None:
        async with self.writer:
            await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS traffic_metrics (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL NOT NULL,
                  p95_latency_ms REAL NOT NULL,
                  error_rate REAL NOT NULL,
                  qps REAL NOT NULL,
                  samples INTEGER NOT NULL,
                  state TEXT NOT NULL,
                  sprt_log_lr REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS system_state (
                  id INTEGER PRIMARY KEY CHECK (id = 1),
                  ts REAL NOT NULL,
                  state TEXT NOT NULL,
                  sha256 TEXT NOT NULL
                );
                """
            )

    async def write_metrics(self, snap: MetricsSnapshot) -> None:
        async with self.writer:
            await asyncio.to_thread(self._write_metrics_sync, snap)

    def _write_metrics_sync(self, snap: MetricsSnapshot) -> None:
        payload = snap.model_dump(mode="json") | {"ts": time.time()}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO traffic_metrics(ts,p95_latency_ms,error_rate,qps,samples,state,sprt_log_lr) VALUES(?,?,?,?,?,?,?)",
                (payload["ts"], snap.p95_latency_ms, snap.error_rate, snap.qps, snap.samples, snap.state.value, snap.sprt_log_lr),
            )
            conn.execute(
                "INSERT INTO system_state(id,ts,state,sha256) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET ts=excluded.ts,state=excluded.state,sha256=excluded.sha256",
                (payload["ts"], snap.state.value, digest),
            )
            conn.execute("COMMIT")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.audit.append("metrics_flush", {"sha256": digest, "state": snap.state.value})

    async def integrity_check(self) -> bool:
        async with self.readers:
            ok = await asyncio.to_thread(self._integrity_check_sync)
        self.audit.append("integrity_check", {"ok": ok})
        return ok

    def _integrity_check_sync(self) -> bool:
        with self.connect() as conn:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    async def backup(self) -> Path:
        async with self.writer:
            return await asyncio.to_thread(self._backup_sync)

    def _backup_sync(self) -> Path:
        backup_dir = self.settings.backup_dir
        manifest_path = self.settings.manifest_path
        assert backup_dir is not None and manifest_path is not None
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"gateway-{int(time.time())}.db"
        with self.connect() as conn:
            conn.execute(f"VACUUM INTO '{target}'")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps({"database": str(target), "sha256": digest, "ts": time.time()}, indent=2))
        backups = sorted(backup_dir.glob("gateway-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[self.settings.backup_keep :]:
            old.unlink(missing_ok=True)
        self.audit.append("backup", {"database": str(target), "sha256": digest})
        return target

    async def restore_manifest(self) -> bool:
        manifest_path = self.settings.manifest_path
        assert manifest_path is not None
        if not manifest_path.exists():
            return False
        manifest = json.loads(manifest_path.read_text())
        source = Path(manifest["database"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["sha256"]:
            self.audit.append("restore_rejected", {"reason": "sha256_mismatch"})
            return False
        shutil.copy2(source, self.db_path)
        self.audit.append("restore_complete", manifest)
        return True
