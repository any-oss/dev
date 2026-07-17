from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Settings
from .models import PolicyState


class CircuitBreaker:
    def __init__(self, fail_max: int, reset_s: float) -> None:
        self.fail_max = fail_max
        self.reset_s = reset_s
        self.failures = 0
        self.opened_at = 0.0

    @property
    def open(self) -> bool:
        if self.failures < self.fail_max:
            return False
        if time.monotonic() - self.opened_at >= self.reset_s:
            self.failures = 0
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.fail_max:
            self.opened_at = time.monotonic()


class Dispatcher:
    """Layer 4: httpx client pool, circuit breaker, and fallback route."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=settings.dispatch_timeout_ms / 1000)
        self.circuit = CircuitBreaker(settings.circuit_fail_max, settings.circuit_reset_s)

    async def close(self) -> None:
        await self.client.aclose()

    async def dispatch(self, payload: dict[str, Any], policy: PolicyState) -> tuple[str, dict[str, Any]]:
        if policy in {PolicyState.FALLBACK, PolicyState.THROTTLE} or self.circuit.open:
            return "fallback", {"text": self.settings.fallback_text, "policy": policy.value}
        try:
            response = await self.client.post(self.settings.upstream_url, json=payload)
            response.raise_for_status()
            self.circuit.record_success()
            return "primary", response.json()
        except Exception as exc:  # upstream isolation boundary
            self.circuit.record_failure()
            return "fallback", {"text": self.settings.fallback_text, "error": type(exc).__name__}
