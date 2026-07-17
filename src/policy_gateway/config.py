from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration for all layers."""

    model_config = SettingsConfigDict(env_prefix="PGW_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    data_dir: Path = Path("var/policy-gateway")
    database_path: Path | None = None
    audit_path: Path | None = None
    manifest_path: Path | None = None
    backup_dir: Path | None = None

    rate_limit_rpm: int = Field(default=120, ge=1)
    max_body_bytes: int = Field(default=1_048_576, ge=1)
    metrics_scrape_gate_ms: int = Field(default=200, ge=1)
    flush_interval_s: float = Field(default=25.0, gt=0)
    integrity_interval_s: float = Field(default=60.0, gt=0)
    backup_interval_s: float = Field(default=900.0, gt=0)
    query_timeout_ms: int = Field(default=150, ge=1)

    ema_alpha: float = Field(default=0.2, gt=0, le=1)
    ring_size: int = Field(default=4096, ge=32)
    qps_high: float = Field(default=320, ge=0)
    qps_low: float = Field(default=280, ge=0)
    p95_latency_ms: float = Field(default=1850, ge=0)
    error_rate_high: float = Field(default=0.045, ge=0, le=1)
    memory_floor_kb: int = Field(default=950_000, ge=1)
    cooldown_ms: int = Field(default=4200, ge=0)
    sprt_accept_h0: float = -1.2
    min_promote_samples: int = Field(default=64, ge=1)

    upstream_url: str = "http://127.0.0.1:8080/completion"
    fallback_text: str = "fallback response from standby cache"
    dispatch_timeout_ms: int = Field(default=1500, ge=1)
    circuit_fail_max: int = Field(default=3, ge=1)
    circuit_reset_s: float = Field(default=30.0, gt=0)
    backup_keep: int = Field(default=3, ge=1)
    audit_max_bytes: int = Field(default=10_485_760, ge=1024)

    oom_score_adj: int | None = Field(default=None, ge=-1000, le=1000)
    fd_soft_limit: int = Field(default=4096, ge=256)

    @field_validator("database_path", "audit_path", "manifest_path", "backup_dir", mode="before")
    @classmethod
    def empty_path_as_none(cls, value: object) -> object:
        return None if value == "" else value

    def resolved(self) -> "Settings":
        data_dir = self.data_dir
        values = self.model_dump()
        values["database_path"] = self.database_path or data_dir / "gateway.db"
        values["audit_path"] = self.audit_path or data_dir / "audit.jsonl"
        values["manifest_path"] = self.manifest_path or data_dir / "manifest.json"
        values["backup_dir"] = self.backup_dir or data_dir / "backups"
        return Settings(**values)
