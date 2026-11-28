"""Structured intent detection and query understanding for the SIMS AI assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional

QUERY_INTENTS = (
    "inventory_lookup",
    "low_stock_products",
    "out_of_stock_products",
    "reorder_recommendations",
    "product_availability",
    "stock_movement",
    "sales_analysis",
    "demand_forecast",
    "inventory_valuation",
    "purchase_recommendations",
    "supplier_queries",
    "general_inventory",
    "business_health",
    "profitability_analysis",
    "revenue_forecast",
    "period_comparison",
    "product_performance",
    "supplier_performance",
)

_SKU_OR_CODE_RE = re.compile(r"\b([A-Za-z0-9]{2,}(?:[_-][A-Za-z0-9]+)+)\b")
_DAYS_HORIZON_RE = re.compile(r"\b(?:next|upcoming|agale|agle)?\s*(\d{1,3})\s*(?:days?|din|दिन)\b", re.IGNORECASE)


@dataclass(frozen=True)
class IntentAnalysis:
    primary_intent: str
    flags: Dict[str, bool] = field(default_factory=dict)
    answer_mode: str = "general"  # count | single_detail | concise_list | full_list | explanation | report | general
    include_all: bool = False
    critical_only: bool = False
    wants_count: bool = False
    wants_explanation: bool = False
    wants_report: bool = False
    forecast_horizon_days: Optional[int] = None
    extracted_skus: List[str] = field(default_factory=list)
    extracted_po_numbers: List[str] = field(default_factory=list)
    has_followup_reference: bool = False
    educational_question: bool = False


def analyze_intent(query: str, page_context: Optional[Dict[str, Any]] = None) -> IntentAnalysis:
    """Classify business intent, answer shape, filters, and follow-up cues accurately."""
    clean = (query or "").strip()
    q = clean.lower()
    page_route = str((page_context or {}).get("route") or "").lower()
    page_product_id = (page_context or {}).get("product_id")
    page_po_id = (page_context or {}).get("purchase_order_id")

    codes = [m.upper() for m in _SKU_OR_CODE_RE.findall(clean)]
    po_numbers = [c for c in codes if c.startswith("PO-")]
    sku_codes = [c for c in codes if not c.startswith("PO-")]

    wants_write_po = any(
        phrase in q
        for phrase in (
            "create po",
            "create a po",
            "draft po",
            "draft purchase order",
            "create purchase order",
            "place po",
            "place a purchase order",
            "po banao",
            "order banao",
            "order create karo",
            "परचेज ऑर्डर बना",
        )
    )

    wants_count = any(
        phrase in q
        for phrase in (
            "how many",
            "count of",
            "number of",
            "total products",
            "total items",
            "kitne",
            "kitni",
            "कितने",
            "कितनी",
            "संख्या",
        )
    )
    # "How many units should I order" is a quantity recommendation, not a product count query
    if any(
        phrase in q
        for phrase in (
            "how many units",
            "how much should i order",
            "how much to order",
            "kitne unit",
            "कितनी इकाई",
        )
    ):
        wants_count = False

    include_all = any(
        phrase in q
        for phrase in (
            "all products",
            "all items",
            "show me all",
            "list all",
            "every product",
            "complete list",
            "complete replenishment",
            "full report",
            "entire inventory",
            "sabhi",
            "saare",
            "सभी",
            "सारे",
            "पूरी सूची",
        )
    )

    wants_report = any(
        phrase in q
        for phrase in (
            "complete replenishment",
            "replenishment report",
            "full report",
            "inventory report",
            "comprehensive report",
            "पूरा विवरण",
            "पूरी रिपोर्ट",
        )
    )
    if wants_report:
        include_all = True

    critical_only = any(
        phrase in q
        for phrase in (
            "critical",
            "most urgent",
            "urgent",
            "highest priority",
            "priority only",
            "सबसे जरूरी",
            "अत्यावश्यक",
        )
    )

    wants_explanation = any(
        phrase in q
        for phrase in (
            "why ",
            "why?",
            "explain",
            "reason",
            "in simple terms",
            "how come",
            "क्यों",
            "समझा",
            "कारण",
            "kyon",
            "kyu",
            "samjhao",
        )
    )

    business_context = any(
        phrase in q
        for phrase in (
            "my business",
            "our business",
            "my store",
            "our store",
            "my supermarket",
            "my sales",
            "our sales",
            "my profit",
            "our profit",
            "my products",
            "our products",
            "my inventory",
            "our inventory",
            "my customers",
            "our customers",
            "my expenses",
            "our expenses",
            "my total",
            "our total",
            "this business",
            "this store",
        )
    ) or any(phrase in q for phrase in ("this month", "last month", "this week", "last week"))
    education_concepts = (
        "forecast",
        "arima",
        "revenue",
        "gross profit",
        "net profit",
        "purchase order",
        "reorder point",
        "inventory turnover",
        "dead stock",
        "working capital",
        "cash flow",
        "demand planning",
        "profit margin",
        "customer behavior",
        "customer lifetime value",
    )
    definition_prefix = re.match(
        r"^(?:what is|what are|define|meaning of|क्या है|क्या होता है)\b",
        q,
    )
    explain_concept = (
        re.match(r"^(?:explain|tell me about|how does|how do|समझाइए|समझाओ)\b", q)
        and any(concept in q for concept in education_concepts)
    )
    educational_question = bool((definition_prefix or explain_concept) and not business_context)

    has_followup_ref = bool(
        re.search(
            r"\b(it|its|this product|that product|this item|that item|the first one|first one|second one|last one|"
            r"which one|most urgent|most critical|this one|that one|iska|iske|uska|uske|woh|yeh|यह|वह|पहला)\b",
            q,
        )
        or (len(q.split()) <= 8 and any(p in q for p in ("should i order", "order quantity", "much to order")))
    )

    # Distinct business condition signals
    wants_out_of_stock = any(
        phrase in q
        for phrase in (
            "out of stock",
            "zero stock",
            "no stock",
            "0 stock",
            "stocked out",
            "finished stock",
            "stock khatam",
            "खत्म हो गया",
            "स्टॉक खत्म",
            "शून्य स्टॉक",
        )
    )

    wants_low_stock = (
        any(
            phrase in q
            for phrase in (
                "running low",
                "low stock",
                "low-stock",
                "below reorder",
                "need attention",
                "shortage",
                "tight stock",
                "kam hai",
                "कम है",
                "स्टॉक कम",
            )
        )
        or critical_only
        or ("/stock-alerts" in page_route)
    )

    wants_reorder = any(
        phrase in q
        for phrase in (
            "reorder",
            "replenish",
            "replenishment",
            "need ordering",
            "should i order",
            "order today",
            "purchase recommendation",
            "suggested order",
            "how much should i order",
            "how many units should i order",
            "kitna order",
            "रीऑर्डर",
            "नया स्टॉक मंगा",
            "ऑर्डर करूं",
            "मंगाना चाहिए",
        )
    ) or ("/reorder-planner" in page_route)

    wants_availability = any(
        phrase in q
        for phrase in (
            "available",
            "availability",
            "in stock",
            "reserved stock",
            "उपलब्ध",
        )
    )

    wants_movement = any(
        phrase in q
        for phrase in (
            "stock movement",
            "inventory log",
            "stock log",
            "stock history",
            "adjustment",
            "stock in",
            "stock out",
            "movement",
            "लेनदेन",
            "स्टॉक इतिहास",
        )
    )

    wants_valuation = any(
        phrase in q
        for phrase in (
            "valuation",
            "inventory value",
            "stock value",
            "worth",
            "capital tied",
            "money blocked",
            "capital invested",
            "money invested",
            "inventory valuation",
            "total value",
            "इन्वेंट्री मूल्य",
            "कुल मूल्य",
        )
    )

    wants_sales = any(
        k in q for k in ("sale", "sales", "revenue", "sold", "top selling", "best seller", "बिक्री", "राजस्व", "बेचा")
    ) or ("/sales" in page_route)

    # Forecast horizon detection
    forecast_horizon_days: Optional[int] = None
    if any(p in q for p in ("next week", "this week", "coming week", "7 days", "अगले सप्ताह", "एक हफ्ते")):
        forecast_horizon_days = 7
    elif any(p in q for p in ("next month", "30 days", "अगले महीने")):
        forecast_horizon_days = 30
    else:
        m_days = _DAYS_HORIZON_RE.search(q)
        if m_days:
            val = int(m_days.group(1))
            if 1 <= val <= 180:
                forecast_horizon_days = val

    wants_forecast = any(
        k in q
        for k in (
            "forecast",
            "predict",
            "demand",
            "run out",
            "stockout",
            "stock out soon",
            "next week",
            "safety stock",
            "days of cover",
            "days of stock",
            "coverage",
            "lead time",
            "पूर्वानुमान",
            "मांग",
            "खत्म होने",
            "अगले सप्ताह",
        )
    ) or ("/forecast" in page_route or "/intelligence" in page_route)

    wants_profit = any(
        phrase in q
        for phrase in (
            "profit",
            "profitable",
            "profitability",
            "gross margin",
            "net margin",
            "expense",
            "expenses",
            "मुनाफा",
            "लाभ",
            "मार्जिन",
        )
    )
    wants_revenue_forecast = wants_sales and wants_forecast and any(
        phrase in q for phrase in ("revenue", "sales", "राजस्व", "बिक्री")
    )
    comparison_requested = any(
        phrase in q
        for phrase in (
            "compare",
            "comparison",
            "compared with",
            "versus",
            " vs ",
            "decreasing",
            "declining",
            "increasing",
            "dropped",
            "गिरावट",
            "घट रहा",
        )
    )
    wants_period_comparison = comparison_requested and (
        wants_sales
        or wants_profit
        or any(phrase in q for phrase in ("this month", "last month", "this week", "last week"))
    )
    if wants_period_comparison:
        wants_sales = True
    wants_business_health = any(
        phrase in q
        for phrase in (
            "business health",
            "business performance",
            "how is my business",
            "how is our business",
            "how is my store",
            "how is our store",
            "health report",
            "what should i improve first",
            "what should i improve today",
            "grow my supermarket",
            "grow my business",
            "how can i increase sales",
            "how can i grow my supermarket",
            "कैसा चल रहा है मेरा कारोबार",
            "मेरा बिजनेस कैसा",
        )
    ) or ("inventory turnover" in q and business_context)
    wants_product_performance = any(
        phrase in q
        for phrase in (
            "top performing product",
            "best performing product",
            "most profitable product",
            "most profitable products",
            "selling poorly",
            "selling best",
            "highest revenue",
            "most revenue",
            "top products",
            "slow moving",
            "slow-moving",
            "low margin",
            "promote",
            "कम बिक",
        )
    ) or (wants_profit and any(p in q for p in ("which product", "which products", "by product")))
    wants_supplier_performance = any(
        phrase in q
        for phrase in (
            "supplier performance",
            "suppliers deliver late",
            "supplier deliver late",
            "late suppliers",
            "supplier offers better pricing",
            "supplier pricing",
            "best supplier",
            "कौन सा सप्लायर देर",
        )
    )
    wants_customer_analysis = any(
        phrase in q
        for phrase in (
            "customer behavior",
            "customer buying",
            "customers buying",
            "what are customers",
            "customer preferences",
        )
    )
    if wants_customer_analysis and any(
        phrase in q for phrase in ("customer buying", "customers buying", "what are customers")
    ):
        educational_question = False
    wants_supplier = any(
        k in q
        for k in (
            "supplier",
            "vendor",
            "purchase order",
            "pending po",
            "pending order",
            "incoming stock",
            "delivery",
            "acknowledge",
            "dispatch",
            "सप्लायर",
            "खरीद",
            "ऑर्डर",
            "डिलीवरी",
        )
    ) or bool(po_numbers) or page_po_id is not None or (
        "/purchase-orders" in page_route or "/suppliers" in page_route or "/supplier-portal" in page_route
    )
    if re.search(r"\bpo\b", q):
        wants_supplier = True

    wants_inventory = (
        wants_low_stock
        or wants_out_of_stock
        or wants_reorder
        or wants_availability
        or wants_valuation
        or wants_write_po
        or bool(sku_codes)
        or page_product_id is not None
        or any(
            k in q
            for k in (
                "stock",
                "inventory",
                "sku",
                "product",
                "products",
                "item",
                "items",
                "स्टॉक",
                "इन्वेंट्री",
                "उत्पाद",
            )
        )
        or ("/products" in page_route or "/inventory" in page_route)
    )

    if educational_question:
        wants_inventory = False
        wants_forecast = False
        wants_sales = False
        wants_supplier = False
        wants_movement = False
        wants_valuation = False
        wants_write_po = False
        wants_profit = False
        wants_revenue_forecast = False
        wants_period_comparison = False
        wants_business_health = False
        wants_product_performance = False
        wants_supplier_performance = False
        wants_customer_analysis = False
    elif wants_product_performance and not any(
        (wants_low_stock, wants_out_of_stock, wants_reorder, wants_availability, wants_valuation)
    ):
        wants_inventory = False
    elif wants_revenue_forecast:
        wants_inventory = False

    # Documentation RAG intent: triggered for uploaded policies/SOPs/manuals/guides OR general non-live questions.
    # Avoid triggering doc noise on live explanation questions like "why is this product running low?".
    doc_signal = any(
        k in q
        for k in (
            "policy",
            "guide",
            "manual",
            "sop",
            "document",
            "uploaded",
            "pdf",
            "spreadsheet",
            "catalog",
            "warranty",
            "return policy",
            "receipt",
            "invitation",
            "sla",
            "workflow",
            "नियम",
            "नीति",
            "दस्तावेज़",
            "कैसे काम",
            "kaise create",
            "kaise kaam",
        )
    )

    has_live_signal = any(
        (
            wants_inventory,
            wants_forecast,
            wants_sales,
            wants_supplier,
            wants_movement,
            wants_valuation,
            wants_write_po,
            has_followup_ref,
            wants_profit,
            wants_period_comparison,
            wants_business_health,
            wants_product_performance,
            wants_supplier_performance,
            wants_customer_analysis,
        )
    )
    wants_docs = doc_signal or (not has_live_signal and not educational_question)

    # Determine primary intent cleanly
    if wants_write_po:
        primary_intent = "purchase_recommendations"
    elif wants_business_health:
        primary_intent = "business_health"
    elif wants_revenue_forecast:
        primary_intent = "revenue_forecast"
    elif wants_period_comparison:
        primary_intent = "period_comparison"
    elif wants_product_performance:
        primary_intent = "product_performance"
    elif wants_supplier_performance:
        primary_intent = "supplier_performance"
    elif wants_customer_analysis:
        primary_intent = "customer_insights"
    elif wants_profit:
        primary_intent = "profitability_analysis"
    elif wants_out_of_stock:
        primary_intent = "out_of_stock_products"
    elif wants_movement:
        primary_intent = "stock_movement"
    elif wants_valuation:
        primary_intent = "inventory_valuation"
    elif wants_forecast and not (wants_low_stock or wants_out_of_stock):
        primary_intent = "demand_forecast"
    elif wants_reorder and not wants_low_stock:
        primary_intent = "reorder_recommendations"
    elif wants_low_stock:
        primary_intent = "low_stock_products"
    elif wants_availability or sku_codes or page_product_id is not None:
        primary_intent = "product_availability" if wants_availability else "inventory_lookup"
    elif wants_sales:
        primary_intent = "sales_analysis"
    elif wants_supplier:
        primary_intent = "supplier_queries"
    elif wants_inventory or has_followup_ref:
        primary_intent = "inventory_lookup"
    else:
        primary_intent = "general_inventory"

    # Determine expected response structure / length
    singular_focus = any(
        p in q for p in ("most critical", "most urgent", "which one", "which product is", "this product", "that product")
    )
    if wants_report:
        answer_mode = "report"
    elif wants_count:
        answer_mode = "count"
    elif include_all:
        answer_mode = "full_list"
    elif wants_explanation:
        answer_mode = "explanation"
    elif sku_codes or page_product_id is not None or singular_focus or (has_followup_ref and not wants_low_stock):
        answer_mode = "single_detail"
    elif primary_intent in (
        "low_stock_products",
        "out_of_stock_products",
        "reorder_recommendations",
        "demand_forecast",
        "stock_movement",
        "supplier_queries",
    ):
        answer_mode = "concise_list"
    else:
        answer_mode = "general"

    flags = {
        "write_po": wants_write_po,
        "inventory": wants_inventory or (wants_forecast and not wants_revenue_forecast) or has_followup_ref,
        "low_stock": wants_low_stock,
        "out_of_stock": wants_out_of_stock,
        "reorder": wants_reorder or wants_write_po,
        "availability": wants_availability,
        "stock_movement": wants_movement,
        "valuation": wants_valuation,
        "po": wants_supplier or wants_write_po,
        "supplier": wants_supplier,
        "sales": wants_sales,
        "forecast": wants_forecast or wants_reorder or wants_low_stock or wants_out_of_stock,
        "docs": wants_docs,
        "education": educational_question,
        "profitability": wants_profit,
        "revenue_forecast": wants_revenue_forecast,
        "period_comparison": wants_period_comparison,
        "business_health": wants_business_health,
        "product_performance": wants_product_performance,
        "supplier_performance": wants_supplier_performance,
        "customer_analysis": wants_customer_analysis,
    }

    return IntentAnalysis(
        primary_intent=primary_intent,
        flags=flags,
        answer_mode=answer_mode,
        include_all=include_all,
        critical_only=critical_only,
        wants_count=wants_count,
        wants_explanation=wants_explanation,
        wants_report=wants_report,
        forecast_horizon_days=forecast_horizon_days,
        extracted_skus=sku_codes,
        extracted_po_numbers=po_numbers,
        has_followup_reference=has_followup_ref,
        educational_question=educational_question,
    )
