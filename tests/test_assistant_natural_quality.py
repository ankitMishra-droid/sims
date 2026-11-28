"""Comprehensive Section 13 evaluation suite: natural responses, data reconciliation, conflicts, follow-ups, and multilingual quality."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.ai_config import AIProviderSettings
from app.core.rate_limiter import reset_rate_limits
from app.database import _set_sqlite_pragma, base, get_db
from app.dependencies.authorization import BusinessContext
from app.main import app
from app.models.business import Business, BusinessMember
from app.models.intelligence import ProductForecast, ReplenishmentRecommendation
from app.models.inventory import InventoryLog
from app.models.products import Product
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus
from app.models.sales import Sale
from app.models.supplier import Supplier
from app.models.users import User
from app.services.ai.business_tools import AuthorizedBusinessTools
from app.services.ai.container import AIRuntimeContainer
from app.services.ai.gemini_client import GeminiClientManager
from app.services.ai.intent_classifier import analyze_intent
from app.services.ai.qdrant_service import QdrantVectorService
from app.services.ai.response_validator import evaluate_response_quality, validate_and_sanitize_response


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _setup_db():
    reset_rate_limits()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return engine, SessionLocal


def _register_and_login(client: TestClient, *, name: str, email: str, biz_name: str, biz_type: str = "retailer") -> Tuple[dict, int]:
    assert client.post(
        "/api/auth/register",
        json={
            "name": name,
            "email": email,
            "password": "Password123!",
            "business_name": biz_name,
            "business_type": biz_type,
            "create_workspace": True,
        },
    ).status_code == 201
    tok = client.post("/api/auth/login", json={"email": email, "password": "Password123!"}).json()["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    biz_id = client.get("/api/auth/me", headers=hdr).json()["active_business_id"]
    return hdr, biz_id


def _make_deterministic_llm_fn(captured: List[Dict[str, str]]):
    """Simulates Gemini using ONLY the assembled structured <business_data> payload to verify end-to-end grounding."""

    def _reply(contents: str, config: Any) -> str:
        sys_inst = str(getattr(config, "system_instruction", "") or "")
        captured.append({"prompt": contents, "system": sys_inst})

        # Extract JSON blocks from <business_data>
        import re

        blocks = re.findall(r"<business_data[^>]*>\s*(.*?)\s*</business_data>", contents, re.DOTALL)
        parsed_data: Dict[str, Any] = {}
        for blk in blocks:
            try:
                obj = json.loads(blk)
                if isinstance(obj, dict) and "products" in obj:
                    parsed_data = obj
                    break
            except Exception:
                continue

        q_match = re.search(r"User Question:\s*(.+)$", contents, re.DOTALL)
        user_q = (q_match.group(1) if q_match else contents).strip()
        q_lower = user_q.lower()

        if "Respond naturally in Hindi" in sys_inst:
            prods = parsed_data.get("products") or []
            count = parsed_data.get("total_count", len(prods))
            if prods:
                first = prods[0]
                return f"{count} उत्पादों का स्टॉक कम है।\n\n1. **{first['name']}** (`{first['sku']}`)\n   - उपलब्ध स्टॉक: {first['stock_available']} इकाई\n   - सुझाया गया ऑर्डर: {first['suggested_order_quantity']} इकाई\n   - प्राथमिकता: {first['priority']}"
            return "अभी किसी उत्पाद का स्टॉक कम नहीं है।"

        if "clear, natural hinglish" in sys_inst.lower():
            prods = parsed_data.get("products") or []
            count = parsed_data.get("total_count", len(prods))
            return f"{count} products ka stock reorder level se neeche hai. Sabse pehle {prods[0]['name']} (`{prods[0]['sku']}`) ko review karein." if prods else "Abhi sabhi products ka stock theek hai."

        # Deliberately inject a subtle [1] / Phase 6 / REORDER_NOW in one case? No, simulate natural model output
        # based strictly on parsed_data (plus test validator separately on noisy LLM outputs!).
        prods = parsed_data.get("products") or []
        warnings = parsed_data.get("data_warnings") or []
        qtype = parsed_data.get("query_type")

        if "how many" in q_lower and "units" not in q_lower:
            if qtype == "out_of_stock_products":
                n = parsed_data.get("out_of_stock_count", len(prods))
                return f"{n} product is currently out of stock." if n == 1 else f"{n} products are currently out of stock."
            n = parsed_data.get("total_count", len(prods))
            return f"{n} products are currently below their reorder thresholds."

        if warnings and not parsed_data.get("physical_stock_verified", True):
            return (
                f"{parsed_data.get('total_count', len(prods))} products are flagged for replenishment. "
                "I couldn't verify their latest physical stock quantities, so please check the inventory records before placing orders."
            )

        if not prods and parsed_data:
            if qtype == "out_of_stock_products":
                return "No products are currently out of stock."
            return "No matching products need attention right now."

        if len(prods) == 1 or "how much should i order" in q_lower or "how many units" in q_lower or "why " in q_lower or "most critical" in q_lower or "most urgent" in q_lower:
            p = prods[0]
            parts = [f"**{p['name']}** (`{p['sku']}`) has {p.get('stock_available')} units available"]
            if p.get("reorder_point") is not None:
                parts.append(f"with a reorder point of {p['reorder_point']} units")
            if p.get("suggested_order_quantity"):
                parts.append(f"Suggested order: {p['suggested_order_quantity']} units")
            if p.get("estimated_days_of_cover") is not None:
                parts.append(f"({p['estimated_days_of_cover']} days of stock coverage)")
            if p.get("priority"):
                parts.append(f"Priority: {p['priority']}")
            return ". ".join(parts) + "."

        lines = [f"{parsed_data.get('total_count', len(prods))} products need attention:\n"]
        for idx, p in enumerate(prods, start=1):
            lines.append(f"{idx}. **{p['name']}** (`{p['sku']}`)")
            lines.append(f"   - Stock available: {p.get('stock_available')} units")
            if p.get("reorder_point") is not None:
                lines.append(f"   - Reorder point: {p['reorder_point']} units")
            if p.get("suggested_order_quantity") is not None:
                lines.append(f"   - Suggested order: {p['suggested_order_quantity']} units")
            if p.get("estimated_days_of_cover") is not None:
                lines.append(f"   - Estimated stock coverage: {p['estimated_days_of_cover']} days")
            if p.get("priority"):
                lines.append(f"   - Priority: {p['priority']}")
            lines.append("")
        return "\n".join(lines).strip()

    return _reply


def _make_container(reply_fn):
    settings = AIProviderSettings(
        app_env="test",
        gemini_api_key="AIzaSyQualityTestKey1234567890",
        gemini_llm_model="gemini-3.5-flash-lite",
        gemini_llm_fallback_models=(),
        gemini_embedding_dimensions=128,
        qdrant_url=":memory:",
        ai_initial_grant_credits=Decimal("1000.0"),
        ai_initial_grant_approved=True,
    )
    mock_genai = MagicMock()

    def _gen(*, model, contents, config):
        txt = reply_fn(contents, config)
        return SimpleNamespace(
            text=txt,
            parsed=None,
            candidates=[SimpleNamespace(finish_reason="STOP", content=SimpleNamespace(parts=[SimpleNamespace(text=txt, thought=False)]))],
            usage_metadata=SimpleNamespace(prompt_token_count=30, candidates_token_count=20, thoughts_token_count=0, total_token_count=50),
        )

    mock_genai.models.generate_content.side_effect = _gen
    mock_genai.models.embed_content.side_effect = lambda *, model, contents, config: SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1] * 128) for _ in contents]
    )
    mem_qdrant = QdrantClient(":memory:")
    container = AIRuntimeContainer(
        settings=settings,
        gemini_client=GeminiClientManager(settings, client=mock_genai),
        qdrant_service=QdrantVectorService(settings, client=mem_qdrant, sleep_fn=lambda _d: None),
    )
    return container, mem_qdrant


# ---------------------------------------------------------------------------
# 1. Intent Classification Coverage (All 12 Query Types)
# ---------------------------------------------------------------------------


def test_intent_classifier_handles_all_business_query_categories():
    cases = [
        ("Which products are running low?", "low_stock_products", "concise_list"),
        ("How many products need reordering?", "reorder_recommendations", "count"),
        ("Which product is most critical?", "low_stock_products", "single_detail"),
        ("What should I reorder today?", "reorder_recommendations", "concise_list"),
        ("Which products are out of stock?", "out_of_stock_products", "concise_list"),
        ("How much stock do we have for SKU FUR-ERG-LXDUAL?", "inventory_lookup", "single_detail"),
        ("Is FUR-ERG-LXDUAL available?", "product_availability", "single_detail"),
        ("Show recent stock movements", "stock_movement", "concise_list"),
        ("Summarize top selling products and sales revenue", "sales_analysis", "general"),
        ("Which products might run out next week?", "demand_forecast", "concise_list"),
        ("What is our total inventory valuation?", "inventory_valuation", "general"),
        ("Show pending supplier deliveries", "supplier_queries", "concise_list"),
        ("Create draft PO for FUR-ERG-LXDUAL 20 units", "purchase_recommendations", "single_detail"),
        ("Show me all products requiring replenishment.", "reorder_recommendations", "full_list"),
        ("How much should I order?", "reorder_recommendations", "single_detail"),
        ("Why is this product running low?", "low_stock_products", "explanation"),
    ]
    for q, expected_intent, _ in cases:
        res = analyze_intent(q)
        assert res.primary_intent == expected_intent, f"Failed for '{q}': got {res.primary_intent}"

    assert analyze_intent("Which products might run out next week?").forecast_horizon_days == 7
    assert analyze_intent("Show me all products requiring replenishment.").include_all is True
    assert analyze_intent("How many products are out of stock?").wants_count is True
    assert analyze_intent("How many units should I order?").wants_count is False
    assert analyze_intent("Which one is the most urgent?").has_followup_reference is True


def test_intent_classifier_separates_education_from_business_analysis():
    education_cases = (
        "What is forecasting?",
        "What is a purchase order?",
        "Explain ARIMA",
        "Explain inventory turnover",
        "What is customer behavior?",
    )
    for query in education_cases:
        intent = analyze_intent(query)
        assert intent.educational_question is True
        assert intent.flags["education"] is True
        assert intent.flags["inventory"] is False
        assert intent.flags["forecast"] is False
        assert intent.flags["docs"] is False

    business_cases = {
        "How is my business performing?": "business_health",
        "How much revenue did I generate this month?": "sales_analysis",
        "Which products generate the highest revenue?": "product_performance",
        "Which products are most profitable?": "product_performance",
        "Why are my sales decreasing?": "period_comparison",
        "Forecast my sales for the next 30 days.": "revenue_forecast",
        "Compare sales this month with last month.": "period_comparison",
        "Which suppliers deliver late?": "supplier_performance",
        "What products should I promote?": "product_performance",
        "What are customers buying most?": "customer_insights",
    }
    for query, expected in business_cases.items():
        intent = analyze_intent(query)
        assert intent.primary_intent == expected, f"Unexpected intent for {query!r}: {intent}"
    assert analyze_intent("Forecast my sales for the next 30 days.").flags["inventory"] is False


def test_sales_analysis_uses_all_rows_and_discloses_missing_costs():
    engine, SessionLocal = _setup_db()
    db = SessionLocal()
    try:
        owner = User(name="Advisor Owner", email="advisor@sims.in", password_hash="x", role="owner")
        db.add(owner)
        db.flush()
        business = Business(name="Advisor Shop", business_type="retailer", owner_user_id=owner.id)
        db.add(business)
        db.flush()
        membership = BusinessMember(
            business_id=business.id,
            user_id=owner.id,
            role="owner",
            is_active=True,
        )
        db.add(membership)
        db.flush()
        context = BusinessContext(
            user=owner,
            business=business,
            membership=membership,
            business_id=business.id,
            role="owner",
        )

        costed_product = Product(
            business_id=business.id,
            sku="COSTED-1",
            name="Costed Rice",
            cost_price=10,
            selling_price=15,
            current_stock=10,
            reorder_level=2,
            is_active=True,
        )
        missing_cost_product = Product(
            business_id=business.id,
            sku="NOCOST-1",
            name="Cost Missing Tea",
            cost_price=0,
            selling_price=20,
            current_stock=5,
            reorder_level=2,
            is_active=True,
        )
        db.add_all([costed_product, missing_cost_product])
        db.flush()
        db.add_all(
            [
                Sale(
                    business_id=business.id,
                    product_id=costed_product.id,
                    sales_date=_utcnow() - timedelta(days=1),
                    quantity_sold=2,
                    selling_price=15,
                    revenue=30,
                    status="COMPLETED",
                ),
                Sale(
                    business_id=business.id,
                    product_id=missing_cost_product.id,
                    sales_date=_utcnow() - timedelta(days=1),
                    quantity_sold=3,
                    selling_price=20,
                    revenue=60,
                    status="COMPLETED",
                ),
            ]
        )
        current_month_start = _utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        db.add(
            Sale(
                business_id=business.id,
                product_id=costed_product.id,
                sales_date=previous_month_start + timedelta(days=2),
                quantity_sold=1,
                selling_price=15,
                revenue=15,
                status="COMPLETED",
            )
        )
        db.add(
            ProductForecast(
                business_id=business.id,
                product_id=costed_product.id,
                horizon_days=30,
                expected_total_demand=8,
                avg_daily_demand=0.27,
                champion_model="TestBaseline",
                data_sufficiency="SUFFICIENT",
                history_days_observed=70,
                is_cold_start=False,
            )
        )
        other_owner = User(name="Other Owner", email="other-advisor@sims.in", password_hash="x", role="owner")
        db.add(other_owner)
        db.flush()
        other_business = Business(
            name="Other Advisor Shop",
            business_type="retailer",
            owner_user_id=other_owner.id,
        )
        db.add(other_business)
        db.flush()
        other_product = Product(
            business_id=other_business.id,
            sku="OTHER-1",
            name="Other Tenant Product",
            cost_price=10,
            selling_price=100,
            current_stock=1,
            reorder_level=0,
            is_active=True,
        )
        db.add(other_product)
        db.flush()
        db.add(
            Sale(
                business_id=other_business.id,
                product_id=other_product.id,
                sales_date=_utcnow() - timedelta(days=1),
                quantity_sold=100,
                selling_price=100,
                revenue=10_000,
                status="COMPLETED",
            )
        )
        db.commit()

        block = AuthorizedBusinessTools.get_sales_summary(
            db, context, query="How much revenue did I generate this month?"
        )
        assert block is not None
        assert block.data["total_revenue"] == 90
        assert block.data["total_units_sold"] == 5
        assert block.data["transaction_count"] == 2
        assert block.data["estimated_gross_profit"] is None
        assert block.data["products_missing_cost_count"] == 1
        assert block.data["net_profit_available"] is False
        assert {row["sku"] for row in block.data["top_products"]} == {"COSTED-1", "NOCOST-1"}
        costed_metrics = next(row for row in block.data["top_products"] if row["sku"] == "COSTED-1")
        assert costed_metrics["estimated_gross_profit"] == 10
        assert all(row["sku"] != "OTHER-1" for row in block.data["top_products"])

        previous_month = AuthorizedBusinessTools.get_sales_summary(
            db, context, query="How much revenue did I generate last month?"
        )
        assert previous_month is not None
        assert previous_month.data["total_revenue"] == 15

        comparison = AuthorizedBusinessTools.get_period_comparison(
            db, context, query="Compare sales this month with last month."
        )
        assert comparison is not None
        assert comparison.data["current_period"]["total_revenue"] == 90
        assert comparison.data["previous_period"]["total_revenue"] == 15
        assert comparison.data["revenue_change_percent"] == 500

        forecast = AuthorizedBusinessTools.get_sales_forecast(db, context, horizon_days=30)
        assert forecast is not None
        forecast_product = forecast.data["products"][0]
        assert forecast_product["expected_demand_units"] == 8
        assert forecast_product["projected_revenue_at_current_price"] == 120
    finally:
        db.close()
        engine.dispose()


def test_educational_question_uses_general_knowledge_without_business_retrieval():
    _engine, _SessionLocal = _setup_db()
    captured: List[Dict[str, str]] = []

    def educational_reply(prompt: str, config: Any) -> str:
        captured.append(
            {
                "prompt": prompt,
                "system": str(getattr(config, "system_instruction", "") or ""),
            }
        )
        return "ARIMA is a forecasting method that learns patterns from past values over time."

    container, mem_qdrant = _make_container(educational_reply)
    app.state.ai_container_override = container
    try:
        with TestClient(app) as client:
            headers, _ = _register_and_login(
                client,
                name="Education User",
                email="education@sims.in",
                biz_name="Education Shop",
            )
            response = client.post(
                "/api/ai/chat",
                headers=headers,
                json={"message": "Explain ARIMA"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["message"]["content"].startswith("ARIMA is a forecasting method")
            assert body["tools_used"] == []
            assert "general knowledge" in captured[-1]["system"]
            mock_client = container.gemini_client._client
            assert mock_client is not None
            assert mock_client.models.embed_content.call_count == 0
    finally:
        app.state.ai_container_override = None
        app.state.ai_container = None
        mem_qdrant.close()
        app.dependency_overrides.clear()


def test_supplier_performance_uses_received_orders_and_comparable_product_costs():
    engine, SessionLocal = _setup_db()
    db = SessionLocal()
    try:
        owner = User(name="Supplier Owner", email="supplier-advisor@sims.in", password_hash="x", role="owner")
        db.add(owner)
        db.flush()
        business = Business(name="Supplier Advisor Shop", business_type="retailer", owner_user_id=owner.id)
        db.add(business)
        db.flush()
        membership = BusinessMember(
            business_id=business.id,
            user_id=owner.id,
            role="owner",
            is_active=True,
        )
        supplier_a = Supplier(business_id=business.id, name="Supplier A", lead_time_days=4, is_active=True)
        supplier_b = Supplier(business_id=business.id, name="Supplier B", lead_time_days=6, is_active=True)
        db.add_all([membership, supplier_a, supplier_b])
        db.flush()
        context = BusinessContext(
            user=owner,
            business=business,
            membership=membership,
            business_id=business.id,
            role="owner",
        )
        product = Product(
            business_id=business.id,
            sku="PRICE-1",
            name="Comparable Product",
            cost_price=10,
            selling_price=15,
            current_stock=1,
            reorder_level=0,
            is_active=True,
        )
        db.add(product)
        db.flush()
        for index, (supplier, unit_cost, delay_days) in enumerate(
            ((supplier_a, 9.0, -1), (supplier_b, 11.0, 2)),
            start=1,
        ):
            expected_date = _utcnow() - timedelta(days=10)
            order = PurchaseOrder(
                business_id=business.id,
                supplier_id=supplier.id,
                order_number=f"PO-ADVISOR-{index}",
                status=PurchaseOrderStatus.RECEIVED,
                total_amount=unit_cost * 5,
                order_date=expected_date - timedelta(days=5),
                expected_delivery_date=expected_date,
                received_at=expected_date + timedelta(days=delay_days),
            )
            db.add(order)
            db.flush()
            db.add(
                PurchaseOrderItem(
                    purchase_order_id=order.id,
                    product_id=product.id,
                    ordered_quantity=5,
                    received_quantity=5,
                    unit_cost=unit_cost,
                )
            )
        db.commit()

        block = AuthorizedBusinessTools.get_supplier_performance(db, context)
        assert block is not None
        assert block.data["received_order_count"] == 2
        assert block.data["pricing_comparison_available"] is True
        price_comparison = block.data["pricing_comparisons"][0]
        assert price_comparison["product"] == "Comparable Product"
        assert [price["average_unit_cost"] for price in price_comparison["supplier_prices"]] == [9, 11]
        performance = {row["supplier"]: row for row in block.data["suppliers"]}
        assert performance["Supplier A"]["on_time_delivery_percent"] == 100
        assert performance["Supplier B"]["average_delivery_delay_days"] == 2
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# 2. Zero Leakage Prompt & Validator Guards + Elimination of 0-vs-9 Conflict
# ---------------------------------------------------------------------------


def test_response_validator_sanitizes_leaked_phases_enums_and_bracket_citations():
    noisy = (
        "Based on the Phase 6 Demand Forecast & Replenishment Intelligence, there are 2 products requiring attention [2].\n"
        "1. Ergotron Arm - Status: REORDER_NOW (CRITICAL) [1]\n"
        "2. Monitor Stand - Status: LOW_STOCK_RISK (INSUFFICIENT_DATA)\n"
        "---\n"
    )
    res = validate_and_sanitize_response(
        noisy,
        allow_document_citations=False,
        reconciled_summary={"headline_count": 2},
    )
    assert "Phase 6" not in res.cleaned_text
    assert "Demand Forecast & Replenishment Intelligence" not in res.cleaned_text
    assert "REORDER_NOW" not in res.cleaned_text
    assert "LOW_STOCK_RISK" not in res.cleaned_text
    assert "INSUFFICIENT_DATA" not in res.cleaned_text
    assert "[1]" not in res.cleaned_text
    assert "[2]" not in res.cleaned_text
    assert "Reorder now" in res.cleaned_text
    assert "Critical priority" in res.cleaned_text
    assert "Not enough data available" in res.cleaned_text
    assert res.sanitized_citations is True
    assert res.sanitized_enums is True
    assert res.sanitized_internal_terms is True

    # Uploaded document citations [1] allowed when document evidence exists, while invalid [9] stripped
    doc_res = validate_and_sanitize_response(
        "Sealed goods can be returned within 14 days [1][9].",
        allow_document_citations=True,
        valid_doc_citation_indices=[1],
    )
    assert "[1]" in doc_res.cleaned_text
    assert "[9]" not in doc_res.cleaned_text


def test_reconciles_live_inventory_with_forecast_eliminates_0_vs_9_mismatch_and_truncation():
    """Reproduces the exact workspace condition: static reorder_level < stock while dynamic ROP triggers 8 REORDER_NOW + 1 healthy-ish DEMAND_DECREASING."""
    _engine, SessionLocal = _setup_db()
    captured: List[Dict[str, str]] = []
    container, mem_qdrant = _make_container(_make_deterministic_llm_fn(captured))
    app.state.ai_container_override = container

    try:
        with TestClient(app) as client:
            hdr, biz_id = _register_and_login(client, name="Retailer", email="reconcile@sims.in", biz_name="WorkGear Pro")
            db = SessionLocal()
            sup = Supplier(business_id=biz_id, name="ErgoSupply", lead_time_days=5, is_active=True)
            db.add(sup)
            db.commit()
            db.refresh(sup)

            # Seed 5 low-stock/reorder products (all ABOVE manual reorder_level!), 1 archived product (must be excluded!),
            # 1 DEMAND_DECREASING non-reorder product, and 1 healthy product.
            items_spec = [
                ("FUR-ERG-LXDUAL", "Ergotron LX Dual Side-by-Side Monitor Arm", 19, 8, True, "REORDER_NOW", "CRITICAL", 47, 56, 4.6),
                ("FUR-UPL-V2-60", "Uplift V2 Standing Desk", 8, 4, True, "REORDER_NOW", "CRITICAL", 22, 27, 4.3),
                ("STR-CRU-64G56", "Crucial Pro 64GB DDR5 RAM Kit", 36, 10, True, "REORDER_NOW", "HIGH", 41, 33, 8.9),
                ("NET-CIS-C9200L", "Cisco Catalyst 9200L Switch", 7, 3, True, "REORDER_NOW", "HIGH", 10, 9, 7.9),
                ("ACC-CAL-TS4", "CalDigit TS4 Docking Station", 12, 6, True, "DEMAND_DECREASING", "INFO", 10, 0, 6.4),
                ("ACC-LOG-MXM3S", "Logitech MX Master 3S", 85, 20, True, "HEALTHY", "LOW", 30, 0, 45.0),
                ("ARC-OLD-ITEM", "Archived Old Monitor", 0, 5, False, "REORDER_NOW", "CRITICAL", 15, 20, 0.0),
            ]
            for sku, name, stock, man_rop, active, rec_type, urg, dyn_rop, sug_qty, cov in items_spec:
                p = Product(
                    business_id=biz_id,
                    sku=sku,
                    name=name,
                    cost_price=100.0,
                    selling_price=150.0,
                    current_stock=stock,
                    reorder_level=man_rop,
                    is_active=active,
                    supplier_id=sup.id,
                )
                db.add(p)
                db.commit()
                db.refresh(p)
                if rec_type != "HEALTHY":
                    db.add(
                        ReplenishmentRecommendation(
                            business_id=biz_id,
                            product_id=p.id,
                            supplier_id=sup.id,
                            recommendation_type=rec_type,
                            urgency=urg,
                            status="NEW",
                            dedup_key=f"biz:{biz_id}:prod:{p.id}:cat:{rec_type}",
                            on_hand_stock=stock,
                            incoming_stock=0,
                            reserved_stock=0,
                            inventory_position=stock,
                            avg_daily_demand=4.1,
                            reorder_point=dyn_rop,
                            suggested_order_qty=sug_qty,
                            days_of_cover_on_hand=cov,
                            days_of_cover_position=cov,
                            explanation_summary="ROP triggered",
                        )
                    )
                    db.commit()
            db.close()

            # 1. "Which products are running low?"
            res = client.post("/api/ai/chat", headers=hdr, json={"message": "Which products are running low?"})
            assert res.status_code == 200, res.text
            body = res.json()
            reply = body["message"]["content"]

            # Strictly excludes DEMAND_DECREASING non-reorder (CalDigit TS4 stock 12 > rop 10) AND archived item -> exact 4 active low items!
            assert body["citations"] == []  # No noisy internal source chips for live inventory!
            prompt_sent = captured[-1]["prompt"]
            sys_sent = captured[-1]["system"]
            assert "Phase 6" not in prompt_sent and "Phase 6" not in sys_sent
            assert "... [truncated]" not in prompt_sent  # Valid non-truncated JSON!
            assert "REORDER_NOW" not in prompt_sent

            qual = evaluate_response_quality(
                reply,
                expected_terms=["4 products", "Ergotron LX", "Uplift V2", "Crucial Pro", "Cisco Catalyst"],
                forbidden_terms=["CalDigit", "Archived Old Monitor", "Phase 6", "REORDER_NOW"],
                allow_citations=False,
            )
            assert qual["passed"], f"Quality failure: {qual}"

            # 2. Multi-turn follow-up: "Which one is the most urgent?" -> "How many units should I order?"
            conv_id = body["conversation"]["id"]
            f1 = client.post("/api/ai/chat", headers=hdr, json={"conversation_id": conv_id, "message": "Which one is the most urgent?"})
            assert f1.status_code == 200
            f1_txt = f1.json()["message"]["content"]
            assert "Uplift V2" in f1_txt or "Ergotron LX" in f1_txt

            f2 = client.post("/api/ai/chat", headers=hdr, json={"conversation_id": conv_id, "message": "How many units should I order?"})
            assert f2.status_code == 200
            f2_txt = f2.json()["message"]["content"]
            assert "27" in f2_txt or "56" in f2_txt

            # 3. Multilingual Hindi + Hinglish check
            hi_res = client.post("/api/ai/chat", headers=hdr, json={"message": "मेरे कौनसे प्रोडक्ट्स का स्टॉक कम है?", "preferred_language": "hi"})
            assert hi_res.status_code == 200
            assert hi_res.json()["response_language"] == "hi"
            assert "FUR-UPL-V2-60" in hi_res.json()["message"]["content"] or "FUR-ERG-LXDUAL" in hi_res.json()["message"]["content"]

            mix_res = client.post("/api/ai/chat", headers=hdr, json={"message": "Kaunse products ka stock kam hai?", "preferred_language": "mixed"})
            assert mix_res.status_code == 200
            assert mix_res.json()["response_language"] == "mixed"
    finally:
        app.state.ai_container_override = None
        app.state.ai_container = None
        mem_qdrant.close()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. All 10 Representative Questions + Pagination + Movements + Valuation
# ---------------------------------------------------------------------------


def test_all_10_representative_questions_and_full_pagination():
    _engine, SessionLocal = _setup_db()
    captured: List[Dict[str, str]] = []
    container, mem_qdrant = _make_container(_make_deterministic_llm_fn(captured))
    app.state.ai_container_override = container

    try:
        with TestClient(app) as client:
            hdr, biz_id = _register_and_login(client, name="AllOps", email="allops@sims.in", biz_name="ScaleStore")
            db = SessionLocal()
            sup = Supplier(business_id=biz_id, name="PrimeVendor", lead_time_days=4, is_active=True)
            db.add(sup)
            db.commit()
            db.refresh(sup)

            # Seed 16 low/reorder SKUs (1 out of stock, 4 critical, 12 high) to verify pagination (> 15 items!) + movements + pending PO
            for i in range(1, 17):
                stock = 0 if i == 1 else (5 + i)
                urg = "CRITICAL" if i <= 4 else "HIGH"
                p = Product(
                    business_id=biz_id,
                    sku=f"ITEM-SKU-{i:03d}",
                    name=f"Warehouse Item {i:02d}",
                    cost_price=50.0,
                    selling_price=80.0,
                    current_stock=stock,
                    reorder_level=3,
                    is_active=True,
                    supplier_id=sup.id,
                )
                db.add(p)
                db.commit()
                db.refresh(p)
                if i == 2:
                    po_in = PurchaseOrder(
                        business_id=biz_id,
                        supplier_id=sup.id,
                        order_number="PO-INCOMING-2",
                        status=PurchaseOrderStatus.SENT,
                        total_amount=500.0,
                    )
                    db.add(po_in)
                    db.commit()
                    db.refresh(po_in)
                    db.add(
                        PurchaseOrderItem(
                            purchase_order_id=po_in.id,
                            product_id=p.id,
                            ordered_quantity=10,
                            received_quantity=0,
                            unit_cost=50.0,
                        )
                    )
                    db.commit()
                db.add(
                    ReplenishmentRecommendation(
                        business_id=biz_id,
                        product_id=p.id,
                        supplier_id=sup.id,
                        recommendation_type="REORDER_NOW",
                        urgency=urg,
                        status="NEW",
                        dedup_key=f"biz:{biz_id}:prod:{p.id}:cat:REORDER_NOW",
                        on_hand_stock=stock,
                        incoming_stock=10 if i == 2 else 0,
                        reserved_stock=0,
                        inventory_position=stock + (10 if i == 2 else 0),
                        avg_daily_demand=3.0,
                        reorder_point=25,
                        suggested_order_qty=30 + i,
                        days_of_cover_on_hand=round(stock / 3.0, 1),
                        days_of_cover_position=round((stock + (10 if i == 2 else 0)) / 3.0, 1),
                        explanation_summary="Lead time demand exceeds current buffer",
                    )
                )
                if i == 1:
                    db.add(
                        InventoryLog(
                            business_id=biz_id,
                            product_id=p.id,
                            movement_type="SALE",
                            stock_in=0,
                            stock_out=5,
                            previous_stock=5,
                            closing_stock=0,
                            reason="recent_order",
                        )
                    )
                db.commit()
            db.close()

            questions = [
                ("Which products are running low?", ["16 products"]),
                ("How many products need reordering?", ["16 products"]),
                ("Which product is most critical?", ["ITEM-SKU-001", "0"]),
                ("What should I reorder today?", ["16 products"]),
                ("Which products are out of stock?", ["ITEM-SKU-001"]),
                ("How much should I order?", ["31"]),
                ("Why is this product running low?", ["ITEM-SKU-001"]),
                ("Show me all products requiring replenishment.", ["16 products", "ITEM-SKU-016"]),
                ("Which products may run out next week?", ["ITEM-SKU-001"]),
                ("Explain the inventory situation in simple terms.", ["16 products"]),
            ]

            for q, must_contain in questions:
                res = client.post("/api/ai/chat", headers=hdr, json={"message": q})
                assert res.status_code == 200, f"{q} failed: {res.text}"
                txt = res.json()["message"]["content"]
                qual = evaluate_response_quality(
                    txt,
                    expected_terms=must_contain,
                    forbidden_terms=["Phase 6", "REORDER_NOW", "LOW_STOCK_RISK"],
                    allow_citations=False,
                )
                assert qual["passed"], f"Query '{q}' failed quality: {qual}\nResponse:\n{txt}"

            # Also verify stock movement and valuation queries hit clean data blocks
            mov_res = client.post("/api/ai/chat", headers=hdr, json={"message": "Show recent stock movements for ITEM-SKU-001"})
            assert mov_res.status_code == 200
            assert "get_stock_movements" in [t["tool"] for t in mov_res.json()["tools_used"]]

            val_res = client.post("/api/ai/chat", headers=hdr, json={"message": "What is our total inventory valuation?"})
            assert val_res.status_code == 200
            assert "get_inventory_valuation" in [t["tool"] for t in val_res.json()["tools_used"]]
    finally:
        app.state.ai_container_override = None
        app.state.ai_container = None
        mem_qdrant.close()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Data Edge Cases & Conflicts: Empty Live Inventory, Duplicates, Null Cover, Pending PO, Reserved, Multi-Tenant
# ---------------------------------------------------------------------------


def test_data_conflict_and_edge_cases_across_inventory_and_forecasting():
    _engine, SessionLocal = _setup_db()
    captured: List[Dict[str, str]] = []
    container, mem_qdrant = _make_container(_make_deterministic_llm_fn(captured))
    app.state.ai_container_override = container

    try:
        with TestClient(app) as client:
            hdr_a, biz_a = _register_and_login(client, name="OwnerA", email="ownera@sims.in", biz_name="Tenant A")
            hdr_b, biz_b = _register_and_login(client, name="OwnerB", email="ownerb@sims.in", biz_name="Tenant B")

            db = SessionLocal()
            sup_a = Supplier(business_id=biz_a, name="SupA", lead_time_days=4, is_active=True)
            sup_b = Supplier(business_id=biz_b, name="SupB", lead_time_days=4, is_active=True)
            db.add_all([sup_a, sup_b])
            db.commit()
            db.refresh(sup_a)
            db.refresh(sup_b)

            # Tenant A: Overlapping SKU, Null days_of_cover, Pending PO incoming stock, Stale forecast date
            p_a1 = Product(
                business_id=biz_a, sku="OVERLAP-SKU-1", name="Alpha Adapter", cost_price=20.0, selling_price=35.0,
                current_stock=0, reorder_level=10, is_active=True, supplier_id=sup_a.id,
            )
            p_a2 = Product(
                business_id=biz_a, sku="DUP-CHECK-SKU", name="Beta Cable Null Cover", cost_price=10.0, selling_price=20.0,
                current_stock=2, reorder_level=5, is_active=True, supplier_id=sup_a.id,
            )
            p_b1 = Product(
                business_id=biz_b, sku="OVERLAP-SKU-1", name="Competitor Beta SKU", cost_price=99.0, selling_price=150.0,
                current_stock=500, reorder_level=5, is_active=True, supplier_id=sup_b.id,
            )
            db.add_all([p_a1, p_a2, p_b1])
            db.commit()
            db.refresh(p_a1)
            db.refresh(p_a2)
            db.refresh(p_b1)

            # Open SENT PO adding incoming stock for p_a1
            po_a = PurchaseOrder(
                business_id=biz_a, supplier_id=sup_a.id, order_number="PO-OPEN-101",
                status=PurchaseOrderStatus.SENT, total_amount=400.0,
            )
            db.add(po_a)
            db.commit()
            db.refresh(po_a)
            db.add(PurchaseOrderItem(purchase_order_id=po_a.id, product_id=p_a1.id, ordered_quantity=20, received_quantity=0, unit_cost=20.0))

            # Stale ProductForecast + Newer Completed Sale
            db.add(
                ProductForecast(
                    business_id=biz_a, product_id=p_a1.id, horizon_days=30,
                    data_cutoff_date=_utcnow() - timedelta(days=10), avg_daily_demand=2.0, expected_total_demand=60.0,
                )
            )
            db.add(Sale(business_id=biz_a, product_id=p_a1.id, quantity_sold=3, selling_price=35.0, revenue=105.0, sales_date=_utcnow(), status="COMPLETED"))

            # Recommendations with missing/null days_of_cover & zero/missing order qty
            db.add(
                ReplenishmentRecommendation(
                    business_id=biz_a, product_id=p_a1.id, supplier_id=sup_a.id,
                    recommendation_type="REORDER_NOW", urgency="CRITICAL", status="NEW",
                    dedup_key=f"biz:{biz_a}:prod:{p_a1.id}:cat:REORDER_NOW",
                    on_hand_stock=0, incoming_stock=20, reserved_stock=0, inventory_position=20,
                    avg_daily_demand=2.0, reorder_point=25, suggested_order_qty=15,
                    days_of_cover_on_hand=0.0, days_of_cover_position=10.0,
                )
            )
            db.add(
                ReplenishmentRecommendation(
                    business_id=biz_a, product_id=p_a2.id, supplier_id=sup_a.id,
                    recommendation_type="LOW_STOCK_RISK", urgency="HIGH", status="NEW",
                    dedup_key=f"biz:{biz_a}:prod:{p_a2.id}:cat:LOW_STOCK_RISK",
                    on_hand_stock=2, incoming_stock=0, reserved_stock=0, inventory_position=2,
                    avg_daily_demand=0.0, reorder_point=5, suggested_order_qty=0,
                    days_of_cover_on_hand=None, days_of_cover_position=None,
                )
            )
            p_a1_id = p_a1.id
            p_a2_id = p_a2.id
            db.commit()
            db.close()

            # A. Incoming PO + Stale Forecast + Null Days-of-Cover + Tenant B Isolation
            res_a = client.post("/api/ai/chat", headers=hdr_a, json={"message": "Which products are running low?"})
            assert res_a.status_code == 200
            prompt_a = captured[-1]["prompt"]
            assert "OVERLAP-SKU-1" in prompt_a
            assert "Competitor Beta SKU" not in prompt_a
            assert "earlier cutoff date" in prompt_a.lower()
            assert "PO-OPEN-101" in prompt_a

            # Tenant B sees ZERO low stock & zero Tenant A leakage
            res_b = client.post("/api/ai/chat", headers=hdr_b, json={"message": "Which products are running low?"})
            assert res_b.status_code == 200
            assert "Alpha Adapter" not in res_b.json()["message"]["content"]
            assert "Beta Cable" not in res_b.json()["message"]["content"]

            # B. Empty live inventory + non-empty forecast conflict: MUST NOT fabricate physical stock!
            with patch(
                "app.services.inventory_service.InventoryService.get_inventory_positions",
                return_value=[],
            ):
                conflict_res = client.post("/api/ai/chat", headers=hdr_a, json={"message": "Which products are running low?"})
                assert conflict_res.status_code == 200
                conflict_prompt = captured[-1]["prompt"]
                assert '"physical_stock_verified": false' in conflict_prompt
                assert '"stock_available": null' in conflict_prompt
                conflict_msg = conflict_res.json()["message"]["content"].lower()
                assert "verify" in conflict_msg and "physical stock" in conflict_msg

            # C. Simulated negative stock, reserved stock & duplicate SKUs handling cleanly
            mocked_positions = [
                {
                    "product_id": None,  # Missing product_id edge case
                    "sku": "ORPHAN", "name": "Bad Row", "on_hand_stock": 1, "incoming_stock": 0,
                    "reserved_stock": 0, "available_stock": 1, "inventory_position": 1, "reorder_level": 5, "unit_cost": 1.0, "inventory_value": 1.0,
                },
                {
                    "product_id": p_a1_id, "sku": "OVERLAP-SKU-1", "name": "Alpha Adapter",
                    "on_hand_stock": 10, "incoming_stock": 20, "reserved_stock": 6,
                    "available_stock": 4, "inventory_position": 24, "reorder_level": 10, "unit_cost": 20.0, "inventory_value": 200.0,
                },
                {
                    "product_id": p_a2_id, "sku": "OVERLAP-SKU-1", "name": "Beta Duplicate SKU",
                    "on_hand_stock": -2, "incoming_stock": 0, "reserved_stock": 0,
                    "available_stock": -2, "inventory_position": -2, "reorder_level": 5, "unit_cost": 10.0, "inventory_value": -20.0,
                },
            ]
            with patch(
                "app.services.inventory_service.InventoryService.get_inventory_positions",
                return_value=mocked_positions,
            ):
                edge_res = client.post("/api/ai/chat", headers=hdr_a, json={"message": "Which products are running low?"})
                assert edge_res.status_code == 200
                edge_prompt = captured[-1]["prompt"]
                assert "Duplicate SKU" in edge_prompt
                assert "missing a product identifier" in edge_prompt
                assert "negative stock" in edge_prompt.lower()
                assert '"stock_available": 4' in edge_prompt
    finally:
        app.state.ai_container_override = None
        app.state.ai_container = None
        mem_qdrant.close()
        app.dependency_overrides.clear()
