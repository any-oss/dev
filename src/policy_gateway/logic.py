from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

from .config import Settings
from .models import MetricsSnapshot, PolicyState


@dataclass(slots=True)
class Sample:
    latency_ms: float
    status_code: int
    ts: float


class EmaSprtEngine:
    """Layer 2: ring-buffer EMA, SPRT-like score, hysteresis policy state machine."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.samples: deque[Sample] = deque(maxlen=settings.ring_size)
        self.ema_p95 = 0.0
        self.ema_error = 0.0
        self.ema_qps = 0.0
        self.sprt_log_lr = 0.0
        self.state = PolicyState.NOMINAL
        self.last_transition = time.monotonic()

    def ingest(self, latency_ms: float, status_code: int) -> MetricsSnapshot:
        now = time.time()
        self.samples.append(Sample(latency_ms, status_code, now))
        return self._recompute(now)

    def reset_buffers(self) -> None:
        self.samples.clear()
        self.ema_p95 = self.ema_error = self.ema_qps = 0.0

    def snapshot(self) -> MetricsSnapshot:
        return MetricsSnapshot(
            p95_latency_ms=round(self.ema_p95, 3),
            error_rate=round(self.ema_error, 6),
            qps=round(self.ema_qps, 3),
            samples=len(self.samples),
            sprt_log_lr=round(self.sprt_log_lr, 6),
            state=self.state,
        )

    def resolve_policy(self, mem_kb: int, cab_approved: bool = False) -> tuple[PolicyState, str, MetricsSnapshot]:
        snap = self.snapshot()
        previous = self.state
        reason = "stable"
        cooldown_expired = (time.monotonic() - self.last_transition) * 1000 >= self.settings.cooldown_ms

        if snap.qps > self.settings.qps_high or mem_kb < self.settings.memory_floor_kb:
            self.state, reason = PolicyState.THROTTLE, "qps_or_memory_bound"
        elif snap.p95_latency_ms > self.settings.p95_latency_ms:
            self.state, reason = PolicyState.DEGRADE, "p95_latency_high"
        elif snap.error_rate > self.settings.error_rate_high:
            self.state, reason = PolicyState.FALLBACK, "error_rate_high"
        elif snap.sprt_log_lr < self.settings.sprt_accept_h0 and cooldown_expired:
            self.state, reason = PolicyState.ACCEPT_H0, "sprt_accept_h0"
            if snap.samples >= self.settings.min_promote_samples and cab_approved:
                self.state, reason = PolicyState.PROMOTE, "cab_approved_promotion"
        elif self.state == PolicyState.THROTTLE and snap.qps <= self.settings.qps_low and cooldown_expired:
            self.state, reason = PolicyState.NOMINAL, "throttle_released"
        elif self.state == PolicyState.DEGRADE and snap.p95_latency_ms <= self.settings.p95_latency_ms and cooldown_expired:
            self.state, reason = PolicyState.NOMINAL, "degrade_recovered"
        elif self.state == PolicyState.FALLBACK and snap.error_rate <= self.settings.error_rate_high and cooldown_expired:
            self.state, reason = PolicyState.NOMINAL, "fallback_recovered"
        elif self.state in {PolicyState.ACCEPT_H0, PolicyState.PROMOTE}:
            reason = self.state.value.lower()
        else:
            self.state = PolicyState.NOMINAL

        if self.state != previous:
            self.last_transition = time.monotonic()
        return self.state, reason, self.snapshot()

    def _recompute(self, now: float) -> MetricsSnapshot:
        latencies = sorted(s.latency_ms for s in self.samples)
        p95 = latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else 0.0
        error_rate = sum(1 for s in self.samples if s.status_code >= 500) / len(self.samples) if self.samples else 0.0
        qps = sum(1 for s in self.samples if now - s.ts <= 1.0)
        alpha = self.settings.ema_alpha
        self.ema_p95 = p95 if self.ema_p95 == 0 else alpha * p95 + (1 - alpha) * self.ema_p95
        self.ema_error = error_rate if self.ema_error == 0 else alpha * error_rate + (1 - alpha) * self.ema_error
        self.ema_qps = qps if self.ema_qps == 0 else alpha * qps + (1 - alpha) * self.ema_qps
        self.sprt_log_lr += math.log(max(1e-9, 1 - error_rate)) - math.log(max(1e-9, 1 - self.settings.error_rate_high))
        return self.snapshot()
