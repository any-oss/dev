from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PolicyState(StrEnum):
    NOMINAL = "NOMINAL"
    THROTTLE = "THROTTLE"
    DEGRADE = "DEGRADE"
    FALLBACK = "FALLBACK"
    ACCEPT_H0 = "ACCEPT_H0"
    PROMOTE = "PROMOTE"


class IngestRequest(BaseModel):
    latency_ms: float = Field(ge=0)
    status_code: int = Field(ge=100, le=599)


class QueuedResponse(BaseModel):
    status: str = "queued"
    ts: float


class DispatchRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    cab_approved: bool = False
    mem_kb: int | None = Field(default=None, ge=0)


class DispatchResponse(BaseModel):
    policy: PolicyState
    reason: str
    route: str
    response: dict[str, Any]
    audit_hash: str


class MetricsSnapshot(BaseModel):
    p95_latency_ms: float = 0
    error_rate: float = 0
    qps: float = 0
    samples: int = 0
    sprt_log_lr: float = 0
    state: PolicyState = PolicyState.NOMINAL
