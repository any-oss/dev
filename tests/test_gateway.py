from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from policy_gateway import Settings, create_app
from policy_gateway.audit import AuditChain
from policy_gateway.logic import EmaSprtEngine
from policy_gateway.models import PolicyState


def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        flush_interval_s=3600,
        integrity_interval_s=3600,
        backup_interval_s=3600,
        dispatch_timeout_ms=25,
        upstream_url="http://127.0.0.1:9/completion",
        cooldown_ms=0,
        min_promote_samples=1,
    ).resolved()


def test_ema_sprt_policy_state_machine(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    engine = EmaSprtEngine(cfg)
    engine.ingest(2000, 200)
    state, reason, snap = engine.resolve_policy(mem_kb=2_000_000)
    assert snap.p95_latency_ms == 2000
    assert state == PolicyState.DEGRADE
    assert reason == "p95_latency_high"

    engine.reset_buffers()
    for _ in range(2):
        engine.ingest(10, 200)
    state, reason, _ = engine.resolve_policy(mem_kb=2_000_000, cab_approved=True)
    assert state in {PolicyState.NOMINAL, PolicyState.ACCEPT_H0, PolicyState.PROMOTE}


def test_ingest_dispatch_metrics_and_rate_limit(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    cfg.rate_limit_rpm = 2
    app = create_app(cfg)
    with TestClient(app) as client:
        first = client.post("/api/v1/ingest", json={"latency_ms": 40, "status_code": 200})
        second = client.post("/api/v1/ingest", json={"latency_ms": 50, "status_code": 200})
        limited = client.post("/api/v1/ingest", json={"latency_ms": 60, "status_code": 200})
        assert first.status_code == 202
        assert second.status_code == 202
        assert limited.status_code == 429

        dispatch = client.post("/api/v1/dispatch", json={"payload": {"prompt": "hi"}, "mem_kb": 2_000_000})
        assert dispatch.status_code == 200
        body = dispatch.json()
        assert body["route"] in {"primary", "fallback"}
        assert body["audit_hash"]

        metrics = client.get("/metrics")
        gated = client.get("/metrics")
        assert metrics.status_code == 200
        assert "policy_gateway_p95_latency_ms" in metrics.text
        assert gated.status_code == 429


def test_sqlite_flush_integrity_backup_and_restore(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    app = create_app(cfg)
    with TestClient(app) as client:
        runtime = client.app.state.runtime
        runtime.logic.ingest(100, 200)
        client.portal.call(runtime.data.write_metrics, runtime.logic.snapshot())
        assert client.portal.call(runtime.data.integrity_check) is True
        backup_path = client.portal.call(runtime.data.backup)
        assert backup_path.exists()
        assert cfg.manifest_path.exists()
        assert client.portal.call(runtime.data.restore_manifest) is True


def test_rollback_endpoint_fails_without_manifest(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        response = client.post("/admin/rollback")
        assert response.status_code == 503


def test_dashboard_static_assets_and_security_headers(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "Policy Gateway Console" in dashboard.text
        assert dashboard.headers["x-content-type-options"] == "nosniff"

        script = client.get("/static/app.js")
        assert script.status_code == 200
        assert "Dispatch probe" not in script.text
        assert "jsonFetch" in script.text


def test_body_size_limit_middleware(tmp_path: Path) -> None:
    cfg = settings(tmp_path)
    cfg.max_body_bytes = 16
    app = create_app(cfg)
    with TestClient(app) as client:
        response = client.post("/api/v1/ingest", json={"latency_ms": 123456, "status_code": 200})
        assert response.status_code == 413



def test_ready_and_audit_verify_endpoints(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        ready = client.get("/ready")
        audit = client.get("/admin/audit/verify")
        assert ready.status_code == 200
        assert ready.json()["database"] is True
        assert audit.status_code == 200
        assert audit.json()["ok"] is True


def test_audit_chain_continues_and_detects_tampering(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    first = AuditChain(audit_path, max_bytes=10_000)
    first_hash = first.append("first", {"value": 1})
    second = AuditChain(audit_path, max_bytes=10_000)
    second_hash = second.append("second", {"value": 2})
    status_payload = second.verify()
    assert status_payload["ok"] is True
    assert status_payload["records"] == 2
    assert status_payload["last_hash"] == second_hash
    assert first_hash != second_hash

    lines = audit_path.read_text().splitlines()
    lines[0] = lines[0].replace('"value": 1', '"value": 99')
    audit_path.write_text("\n".join(lines) + "\n")
    assert AuditChain(audit_path, max_bytes=10_000).verify()["ok"] is False


def test_team_b_layout_config_loader_and_facades() -> None:
    from config_loader import load_layer_config, settings_from_layers
    from layer_0.resource import mem_available_kb
    from layer_1.data import DataStore
    from layer_2.logic import EmaSprtEngine as LayerEngine
    from layer_3.api import create_app as layer_create_app
    from layer_4.dispatch import Dispatcher
    from layer_5.orchestrator import create_app as orch_create_app
    from observability.exporter import PROMETHEUS_CONTENT_TYPE

    merged = load_layer_config("config")
    cfg = settings_from_layers("config")
    assert merged["rate_limit_rpm"] == 120
    assert cfg.port == 8000
    assert mem_available_kb() > 0
    assert DataStore.__name__ == "DataStore"
    assert LayerEngine.__name__ == "EmaSprtEngine"
    assert layer_create_app is orch_create_app
    assert Dispatcher.__name__ == "Dispatcher"
    assert PROMETHEUS_CONTENT_TYPE.startswith("text/plain")


def test_settings_from_environment_uses_config_dir(monkeypatch) -> None:
    from config_loader import settings_from_environment

    monkeypatch.setenv("PGW_CONFIG_DIR", "config")
    cfg = settings_from_environment()
    assert cfg.port == 8000
    assert cfg.upstream_url == "http://127.0.0.1:8080/completion"
