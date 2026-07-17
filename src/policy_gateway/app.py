from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from importlib import resources
from typing import AsyncIterator

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .audit import AuditChain
from .config import Settings
from .data import DataStore
from .dispatch import Dispatcher
from .infra import enforce_resource_governance, mem_available_kb
from .logic import EmaSprtEngine
from .models import DispatchRequest, DispatchResponse, IngestRequest, MetricsSnapshot, PolicyState, QueuedResponse


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header_map = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = header_map.get(b"content-length")
        if content_length:
            try:
                too_large = int(content_length) > self.max_body_bytes
            except ValueError:
                too_large = True
            if too_large:
                response = PlainTextResponse("request body too large", status_code=413)
                await response(scope, receive, send)
                return
        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_body_bytes:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "request body too large")
            return message

        try:
            await self.app(scope, limited_receive, send)
        except HTTPException as exc:
            response = PlainTextResponse(str(exc.detail), status_code=exc.status_code)
            await response(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ])
            await send(message)
        await self.app(scope, receive, send_with_headers)


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.rpm = rpm
        self.events: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        now = time.monotonic()
        window = now - 60
        bucket = [ts for ts in self.events.get(key, []) if ts >= window]
        if len(bucket) >= self.rpm:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded")
        bucket.append(now)
        self.events[key] = bucket


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings.resolved()
        self.audit = AuditChain(self.settings.audit_path, self.settings.audit_max_bytes)  # type: ignore[arg-type]
        self.logic = EmaSprtEngine(self.settings)
        self.data = DataStore(self.settings, self.audit)
        self.dispatcher = Dispatcher(self.settings)
        self.rate_limiter = RateLimiter(self.settings.rate_limit_rpm)
        self.last_scrape = 0.0
        self.tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        governance = enforce_resource_governance(self.settings)
        self.audit.append("boot", {"governance": governance})
        await self.data.initialize()
        self.tasks = [
            asyncio.create_task(self._flush_loop()),
            asyncio.create_task(self._integrity_loop()),
            asyncio.create_task(self._backup_loop()),
        ]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.dispatcher.close()
        self.audit.append("shutdown", {})

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.flush_interval_s)
            await self.data.write_metrics(self.logic.snapshot())
            self.logic.reset_buffers()

    async def _integrity_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.integrity_interval_s)
            ok = await self.data.integrity_check()
            if not ok:
                self.audit.append("rollback_required", {"reason": "integrity_check_failed"})

    async def _backup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.backup_interval_s)
            await self.data.backup()


def get_state(request: Request) -> AppState:
    return request.app.state.runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = AppState(settings or Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="Policy Gateway", version="0.2.0", lifespan=lifespan)
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=runtime.settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    static_dir = resources.files("policy_gateway").joinpath("static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    async def health(state: AppState = Depends(get_state)) -> dict[str, object]:
        return {"status": "ok", "state": state.logic.snapshot().state, "ts": time.time()}

    @app.get("/ready")
    async def ready(state: AppState = Depends(get_state)) -> dict[str, object]:
        db_ok = await state.data.integrity_check()
        audit_status = state.audit.verify()
        if not db_ok or not audit_status["ok"]:
            raise HTTPException(503, {"database": db_ok, "audit": audit_status})
        return {"status": "ready", "database": db_ok, "audit": audit_status}

    @app.post("/api/v1/ingest", response_model=QueuedResponse, status_code=status.HTTP_202_ACCEPTED)
    async def ingest(req: Request, body: IngestRequest, state: AppState = Depends(get_state)) -> QueuedResponse:
        state.rate_limiter.check(req.client.host if req.client else "unknown")
        snap = state.logic.ingest(body.latency_ms, body.status_code)
        state.audit.append("ingest_queued", snap.model_dump(mode="json"))
        return QueuedResponse(ts=time.time())

    @app.post("/api/v1/dispatch", response_model=DispatchResponse)
    async def dispatch(body: DispatchRequest, state: AppState = Depends(get_state)) -> DispatchResponse:
        mem_kb = body.mem_kb if body.mem_kb is not None else mem_available_kb()
        policy, reason, snap = state.logic.resolve_policy(mem_kb, body.cab_approved)
        if policy == PolicyState.DEGRADE:
            body.payload.setdefault("context_limit", 1024)
            body.payload["clear_kv_cache"] = True
        route, payload = await state.dispatcher.dispatch(body.payload, policy)
        audit_hash = state.audit.append("dispatch", {"policy": policy.value, "reason": reason, "route": route, "metrics": snap.model_dump(mode="json")})
        return DispatchResponse(policy=policy, reason=reason, route=route, response=payload, audit_hash=audit_hash)

    @app.get("/metrics")
    async def metrics(state: AppState = Depends(get_state)) -> Response:
        now = time.monotonic()
        if (now - state.last_scrape) * 1000 < state.settings.metrics_scrape_gate_ms:
            return PlainTextResponse("scrape gate active\n", status_code=429)
        state.last_scrape = now
        snap: MetricsSnapshot = state.logic.snapshot()
        lines = [
            f'policy_gateway_state{{state="{snap.state.value}"}} 1',
            f"policy_gateway_p95_latency_ms {snap.p95_latency_ms}",
            f"policy_gateway_error_rate {snap.error_rate}",
            f"policy_gateway_qps {snap.qps}",
            f"policy_gateway_samples {snap.samples}",
            f"policy_gateway_sprt_log_lr {snap.sprt_log_lr}",
        ]
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.get("/admin/audit/verify")
    async def verify_audit(state: AppState = Depends(get_state)) -> dict[str, object]:
        status_payload = state.audit.verify()
        if not status_payload["ok"]:
            raise HTTPException(503, status_payload)
        return status_payload

    @app.post("/admin/rollback")
    async def rollback(state: AppState = Depends(get_state)) -> dict[str, object]:
        restored = await state.data.restore_manifest()
        ok = await state.data.integrity_check() if restored else False
        if not ok:
            raise HTTPException(503, "rollback verification failed")
        return {"status": "online", "restored": restored}

    return app
