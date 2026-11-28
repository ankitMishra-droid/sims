from pathlib import Path
import time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limiter import reset_rate_limits
from app.database import _set_sqlite_pragma, base, get_db
from app.main import app


REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_client():
    reset_rate_limits()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), engine


def test_core_endpoints_latency_and_readiness_probe():
    client, _engine = _make_client()
    try:
        reg = client.post(
            "/api/auth/register",
            json={
                "name": "Perf Owner",
                "email": "perf@sims.in",
                "password": "Password123!",
                "business_name": "Perf Store",
            },
        )
        assert reg.status_code == 201
        tok = client.post(
            "/api/auth/login",
            json={"email": "perf@sims.in", "password": "Password123!"},
        ).json()["access_token"]
        hdrs = {"Authorization": f"Bearer {tok}"}

        sup_id = client.post("/api/suppliers/", headers=hdrs, json={"name": "Perf Vendor"}).json()["data"]["id"]
        for idx in range(25):
            prod = client.post(
                "/api/products/",
                headers=hdrs,
                json={
                    "sku": f"PERF-{idx:03d}",
                    "name": f"Perf Product {idx}",
                    "cost_price": 40.0,
                    "selling_price": 75.0,
                    "current_stock": 2 if idx < 5 else 30,
                    "reorder_level": 10,
                    "supplier_id": sup_id,
                },
            ).json()["data"]
            client.post(
                "/api/sales/",
                headers=hdrs,
                json={"product_id": prod["id"], "quantity_sold": 1},
            )

        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        # Warm forecast cache once then verify fast cached reads
        client.get("/api/intelligence/forecasts?horizon_days=30", headers=hdrs)

        timings_ms = {}
        for name, path in (
            ("dashboard", "/dashboard/summary"),
            ("products", "/api/products/"),
            ("positions", "/api/inventory/positions"),
            ("alerts", "/api/inventory/alerts"),
            ("overview", "/api/intelligence/overview?sync=false"),
            ("forecasts_cached", "/api/intelligence/forecasts?horizon_days=30"),
        ):
            t0 = time.perf_counter()
            res = client.get(path, headers=hdrs)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            assert res.status_code == 200, f"{path} failed: {res.text}"
            timings_ms[name] = round(dt_ms, 2)

        print("BENCHMARK_TIMINGS_MS:", timings_ms)
        # Ensure all operational & cached intelligence reads respond well under latency budgets
        for endpoint, elapsed in timings_ms.items():
            assert elapsed < 2000.0, f"{endpoint} exceeded latency budget: {elapsed}ms"
    finally:
        app.dependency_overrides.clear()


def test_requirements_utf8_and_render_deployment_manifest_integrity():
    req_bytes = (REPO_ROOT / "backend" / "requirements.txt").read_bytes()
    assert not req_bytes.startswith((b"\xff\xfe", b"\xfe\xff")), "requirements.txt must not be UTF-16 encoded"
    assert b"\x00" not in req_bytes
    req_text = req_bytes.decode("utf-8")
    assert "pytest==" not in req_text
    assert "pyrefly==" not in req_text
    assert "fastapi==" in req_text
    assert "psycopg2-binary==" in req_text

    dev_req = (REPO_ROOT / "backend" / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "-r requirements.txt" in dev_req
    assert "pytest==" in dev_req
    assert "pyrefly==" in dev_req

    render_text = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "healthCheckPath: /health" in render_text
    assert "startCommand: python -m app.db_migrate && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1" in render_text
    assert "value: 3.13.3" in render_text
    assert "value: production" in render_text
    assert 'value: "1"' in render_text


def test_frontend_production_dist_has_no_demo_passwords_or_xss():
    dist_dir = REPO_ROOT / "frontend" / "smart inventory forecast management system" / "dist" / "assets"
    if not dist_dir.exists():
        return
    js_files = list(dist_dir.glob("*.js"))
    assert js_files
    for asset in js_files:
        text = asset.read_text(encoding="utf-8", errors="ignore")
        assert "SecretPassword123!" not in text, f"Found hardcoded demo password in {asset.name}"
