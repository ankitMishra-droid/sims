"""Layer 1-6 orchestration: intent analysis, reconciled tools, grounded generation, and response validation."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from ...core.ai_exceptions import AIErrorCode, AIInvalidRequestError, AIServiceError
from ...core.ai_logging import get_ai_logger, log_ai_event
from ...core.ai_pricing import CostBreakdown, credits_float, from_credit_units
from ...dependencies.authorization import BusinessContext
from ...models.ai_rag import AIConversation, AICreditAccount, AIMessage, AIUsageLog
from ...models.products import Product
from .business_tools import AuthorizedBusinessTools
from .container import AIRuntimeContainer
from .context_assembly import ToolEvidenceBlock, assemble_grounded_context
from .conversation_service import ConversationService
from .credit_service import CreditReservation
from .intent_classifier import IntentAnalysis, analyze_intent
from .language_detection import detect_language
from .response_validator import validate_and_sanitize_response
from .retrieval_service import TenantHybridRetrievalService


def _classify_error_category(exc: AIServiceError) -> str:
    code = exc.error_code
    if code == AIErrorCode.QUOTA_EXHAUSTED:
        return "quota"
    if code == AIErrorCode.RATE_LIMIT_RETRYABLE:
        return "rate_limit"
    if code == AIErrorCode.CIRCUIT_OPEN:
        return "circuit_open"
    if code == AIErrorCode.TIMEOUT_ERROR:
        return "timeout"
    if code in (
        AIErrorCode.AUTHENTICATION_ERROR,
        AIErrorCode.PERMISSION_DENIED,
        AIErrorCode.PROVIDER_UNCONFIGURED,
        AIErrorCode.INVALID_MODEL,
    ):
        return "provider_config"
    if exc.retryable:
        return "transient"
    return "client"


class SIMSAssistantService:
    """Orchestrates query understanding, reconciled business tools, RAG, generation, and validation."""

    def __init__(self, container: AIRuntimeContainer) -> None:
        self._container = container
        self._settings = container.settings
        self._retrieval = TenantHybridRetrievalService(container)
        self._logger = get_ai_logger("assistant")

    @staticmethod
    def _classify_intents(query: str, page_context: Optional[Dict[str, Any]]) -> Dict[str, bool]:
        """Backwards-compatible boolean intent flags derived from structured IntentAnalysis."""
        return dict(analyze_intent(query, page_context).flags)

    @staticmethod
    def _resolve_followup_products(
        db: Session,
        *,
        business_id: int,
        current_query: str,
        recent_turns: Sequence[Tuple[str, str]],
        intent: IntentAnalysis,
    ) -> Tuple[List[int], Optional[str]]:
        """Resolve pronoun/ordinal references (`it`, `the first one`, `most urgent`) to fresh tenant Product IDs."""
        if not intent.has_followup_reference or intent.extracted_skus or not recent_turns:
            return [], None

        active_products = (
            db.query(Product)
            .filter(Product.business_id == business_id, Product.is_active.is_(True))
            .order_by(Product.id.asc())
            .all()
        )
        if not active_products:
            return [], None

        ordered_matches: List[Tuple[int, Product]] = []
        for role, text in reversed(recent_turns):
            if role not in ("assistant", "user") or not text:
                continue
            txt_lower = text.lower()
            txt_upper = text.upper()
            found_in_turn: List[Tuple[int, Product]] = []
            for p in active_products:
                pos = -1
                sku_u = (p.sku or "").strip().upper()
                if sku_u and sku_u in txt_upper:
                    pos = txt_upper.find(sku_u)
                else:
                    name_l = (p.name or "").strip().lower()
                    if name_l and name_l in txt_lower:
                        pos = txt_lower.find(name_l)
                    else:
                        # Match core prefix before parentheses, e.g. 'MacBook Pro 14"' or 'Uplift V2 Standing Desk'
                        short_name = re.split(r"\s*\(", name_l)[0].strip()
                        if len(short_name) >= 5 and short_name in txt_lower:
                            pos = txt_lower.find(short_name)
                if pos >= 0:
                    found_in_turn.append((pos, p))
            if found_in_turn:
                found_in_turn.sort(key=lambda pair: pair[0])
                ordered_matches = found_in_turn
                break

        if not ordered_matches:
            return [], None

        q_lower = current_query.lower()
        products_ordered = [p for _, p in ordered_matches]

        chosen: List[Product]
        if any(w in q_lower for w in ("second", "2nd", "दूसरा")) and len(products_ordered) >= 2:
            chosen = [products_ordered[1]]
        elif any(w in q_lower for w in ("third", "3rd", "तीसरा")) and len(products_ordered) >= 3:
            chosen = [products_ordered[2]]
        elif any(w in q_lower for w in ("last", "आखिरी")):
            chosen = [products_ordered[-1]]
        elif any(w in q_lower for w in ("first", "1st", "पहला")):
            chosen = [products_ordered[0]]
        elif intent.critical_only:
            # Pass all candidate items from prior turn so reconciled live ranking selects highest urgency
            chosen = products_ordered
        elif len(products_ordered) == 1:
            chosen = products_ordered
        else:
            # For singular follow-ups like "How many units should I order?", focus on top-ranked prior item
            chosen = [products_ordered[0]]

        if len(chosen) == 1:
            note = f"User follow-up refers to {chosen[0].name} (SKU: {chosen[0].sku}). Use the refreshed live numbers provided."
        else:
            names = ", ".join(f"{p.name} ({p.sku})" for p in chosen[:5])
            note = f"User follow-up refers to these previously discussed products: {names}. Use the refreshed live numbers provided."

        return [p.id for p in chosen], note

    def chat(
        self,
        db: Session,
        ctx: BusinessContext,
        *,
        message: str,
        conversation_id: Optional[int] = None,
        preferred_language: str = "auto",
        page_context: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        req_id = str(uuid4())
        clean_msg = (message or "").strip()
        if not clean_msg:
            raise AIInvalidRequestError("Message text must not be empty.", provider="assistant")

        # 1. Verify existing conversation ownership (defer creating a new one until credits & policies pass)
        conv: Optional[AIConversation] = None
        if conversation_id is not None:
            conv = ConversationService.require_owned_conversation(
                db,
                conv_id=conversation_id,
                business_id=ctx.business_id,
                user_id=ctx.user.id,
            )

        detected_query_lang = detect_language(clean_msg).language
        conv_pref = conv.preferred_language if conv is not None else preferred_language
        if preferred_language in ("auto", "en", "hi", "mixed"):
            target_pref = preferred_language
        else:
            target_pref = conv_pref if conv_pref in ("auto", "en", "hi", "mixed") else "auto"
        effective_lang = (
            target_pref
            if target_pref in ("en", "hi", "mixed")
            else (detected_query_lang if detected_query_lang in ("en", "hi", "mixed") else "en")
        )

        credit_acc = (
            db.query(AICreditAccount)
            .filter(AICreditAccount.business_id == ctx.business_id)
            .first()
        )
        max_turns = (
            credit_acc.max_context_turns
            if credit_acc and credit_acc.max_context_turns is not None
            else getattr(self._settings, "ai_max_conversation_turns", 8)
        )

        # Gather bounded recent context without mutating DB before credit reservation
        if conv is not None:
            summary_text, recent_turns, prev_user = ConversationService.get_bounded_recent_turns(
                db,
                conv=conv,
                max_turns=max_turns,
            )
        else:
            summary_text, recent_turns, prev_user = None, [], None

        # Layer 1: Structured Intent Analysis + Follow-Up Product Resolution
        intent = analyze_intent(clean_msg, page_context)
        focus_product_ids, followup_note = self._resolve_followup_products(
            db,
            business_id=ctx.business_id,
            current_query=clean_msg,
            recent_turns=recent_turns,
            intent=intent,
        )

        # Layer 2 & 3: Authorized Reconciled Data Retrieval & Validation
        tool_blocks: List[ToolEvidenceBlock] = []
        executed_tools: List[Dict[str, Any]] = []
        pending_action: Optional[Dict[str, Any]] = None
        reconciled_summary: Optional[Dict[str, Any]] = None
        expected_skus: List[str] = list(intent.extracted_skus)

        if (ctx.business.business_type or "").lower() == "supplier":
            if intent.flags.get("supplier") or intent.flags.get("po"):
                sp_block = AuthorizedBusinessTools.get_supplier_portal_orders(db, ctx)
                if sp_block:
                    tool_blocks.append(sp_block)
                    executed_tools.append({"tool": sp_block.tool_name, "source": sp_block.source_kind})
        else:
            if intent.flags.get("valuation"):
                val_block = AuthorizedBusinessTools.get_inventory_valuation(
                    db, ctx, include_all=intent.include_all
                )
                if val_block:
                    tool_blocks.append(val_block)
                    executed_tools.append({"tool": val_block.tool_name, "source": val_block.source_kind})

            if intent.flags.get("stock_movement"):
                mov_block = AuthorizedBusinessTools.get_stock_movements(
                    db, ctx, query=clean_msg, focus_product_ids=focus_product_ids
                )
                if mov_block:
                    tool_blocks.append(mov_block)
                    executed_tools.append({"tool": mov_block.tool_name, "source": mov_block.source_kind})

            needs_reconciled_inventory = any(
                intent.flags.get(k)
                for k in (
                    "inventory",
                    "low_stock",
                    "out_of_stock",
                    "reorder",
                    "availability",
                    "write_po",
                )
            ) or bool(focus_product_ids)
            needs_reconciled_inventory = needs_reconciled_inventory or (
                intent.flags.get("forecast") and not intent.flags.get("revenue_forecast")
            )

            if needs_reconciled_inventory:
                inv_intel_block, focus_meta = AuthorizedBusinessTools.get_reconciled_inventory_intelligence(
                    db,
                    ctx,
                    intent=intent,
                    query=clean_msg,
                    page_context=page_context,
                    focus_product_ids=focus_product_ids,
                )
                if inv_intel_block:
                    tool_blocks.append(inv_intel_block)
                    executed_tools.append({"tool": inv_intel_block.tool_name, "source": inv_intel_block.source_kind})
                    expected_skus.extend(
                        str(item["sku"]) for item in focus_meta if item.get("sku")
                    )
                    if isinstance(inv_intel_block.data, dict):
                        headline = (
                            inv_intel_block.data.get("out_of_stock_count")
                            if intent.primary_intent == "out_of_stock_products"
                            else inv_intel_block.data.get("total_count")
                        )
                        reconciled_summary = {"headline_count": headline}

            if intent.flags.get("po") or intent.flags.get("supplier"):
                for tb in AuthorizedBusinessTools.get_purchase_orders_and_suppliers(
                    db, ctx, query=clean_msg, page_context=page_context
                ):
                    tool_blocks.append(tb)
                    executed_tools.append({"tool": tb.tool_name, "source": tb.source_kind})

            if intent.flags.get("business_health"):
                health_block = AuthorizedBusinessTools.get_business_health_summary(db, ctx)
                if health_block:
                    tool_blocks.append(health_block)
                    executed_tools.append({"tool": health_block.tool_name, "source": health_block.source_kind})

            if intent.flags.get("profitability"):
                profit_block = AuthorizedBusinessTools.get_profitability_analysis(
                    db, ctx, query=clean_msg
                )
                if profit_block:
                    tool_blocks.append(profit_block)
                    executed_tools.append({"tool": profit_block.tool_name, "source": profit_block.source_kind})

            if intent.flags.get("period_comparison"):
                comparison_block = AuthorizedBusinessTools.get_period_comparison(
                    db, ctx, query=clean_msg
                )
                if comparison_block:
                    tool_blocks.append(comparison_block)
                    executed_tools.append({"tool": comparison_block.tool_name, "source": comparison_block.source_kind})

            if intent.flags.get("revenue_forecast"):
                forecast_block = AuthorizedBusinessTools.get_sales_forecast(
                    db,
                    ctx,
                    horizon_days=intent.forecast_horizon_days or 30,
                )
                if forecast_block:
                    tool_blocks.append(forecast_block)
                    executed_tools.append({"tool": forecast_block.tool_name, "source": forecast_block.source_kind})

            if intent.flags.get("supplier_performance"):
                supplier_block = AuthorizedBusinessTools.get_supplier_performance(db, ctx)
                if supplier_block:
                    tool_blocks.append(supplier_block)
                    executed_tools.append({"tool": supplier_block.tool_name, "source": supplier_block.source_kind})

            if intent.flags.get("customer_analysis"):
                customer_block = ToolEvidenceBlock(
                    tool_name="customer_data_availability",
                    source_kind="business_tool",
                    summary="Customer-level sales records are not available in this workspace",
                    data={
                        "query_type": "customer_insights",
                        "available": False,
                        "reason": (
                            "SIMS does not currently store customer-level identities or transaction history, "
                            "so customer preferences and buying behavior cannot be measured."
                        ),
                    },
                    include_in_user_citations=False,
                )
                tool_blocks.append(customer_block)
                executed_tools.append({"tool": customer_block.tool_name, "source": customer_block.source_kind})

            if intent.flags.get("sales") and not any(
                intent.flags.get(flag)
                for flag in ("profitability", "period_comparison", "business_health", "revenue_forecast")
            ):
                sales_block = AuthorizedBusinessTools.get_sales_summary(
                    db,
                    ctx,
                    query=clean_msg,
                    rank_by_profit=bool(intent.flags.get("product_performance") and intent.flags.get("profitability")),
                )
                if sales_block:
                    tool_blocks.append(sales_block)
                    executed_tools.append({"tool": sales_block.tool_name, "source": sales_block.source_kind})

            if intent.flags.get("product_performance") and not intent.flags.get("profitability"):
                product_block = AuthorizedBusinessTools.get_sales_summary(
                    db, ctx, query=clean_msg
                )
                if product_block:
                    product_block = ToolEvidenceBlock(
                        tool_name="get_product_performance",
                        source_kind=product_block.source_kind,
                        summary="Product sales performance",
                        data={**product_block.data, "query_type": "product_performance"},
                        include_in_user_citations=False,
                    )
                    tool_blocks.append(product_block)
                    executed_tools.append({"tool": product_block.tool_name, "source": product_block.source_kind})

            if intent.flags.get("write_po"):
                try:
                    pending_action = AuthorizedBusinessTools.prepare_draft_po_proposal(
                        db,
                        ctx,
                        query=clean_msg,
                        page_context=page_context,
                        focus_product_ids=focus_product_ids,
                    )
                    if pending_action:
                        tool_blocks.append(
                            ToolEvidenceBlock(
                                tool_name="prepare_draft_purchase_order",
                                source_kind="business_tool",
                                summary="Prepared draft purchase order awaiting confirmation",
                                data=pending_action,
                                include_in_user_citations=False,
                            )
                        )
                        executed_tools.append({"tool": "prepare_draft_purchase_order", "source": "business_tool"})
                except AIServiceError as perm_err:
                    tool_blocks.append(
                        ToolEvidenceBlock(
                            tool_name="prepare_draft_purchase_order",
                            source_kind="business_tool",
                            summary="Draft purchase order permission notice",
                            data={"authorized": False, "reason": perm_err.message},
                            include_in_user_citations=False,
                        )
                    )

        # Reserve credits atomically BEFORE any external Gemini/Qdrant call & release DB lock cleanly
        need_rag_docs = bool(intent.flags.get("docs") and not intent.flags.get("education"))
        est_prompt_chars = (
            len(clean_msg)
            + len(summary_text or "")
            + sum(len(t) for _, t in recent_turns)
            + sum(len(json.dumps(tb.data, default=str)) for tb in tool_blocks)
            + 1200
        )
        reserve_units = self._container.pricing.estimate_max_chat_reserve_units(
            model_name=self._settings.gemini_llm_model,
            prompt_chars=est_prompt_chars,
            max_output_tokens=getattr(self._settings, "gemini_max_output_tokens", 1024),
        )
        if (
            need_rag_docs
            and self._container.gemini_client.is_configured
            and self._container.qdrant_service.is_configured
        ):
            reserve_units += self._container.pricing.estimate_embedding_batch_reserve_units(
                model_name=self._settings.gemini_embedding_model,
                texts=[clean_msg],
                include_chunk_fee=False,
            )

        reservation: CreditReservation = self._container.credit_service.reserve_credits(
            db,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
            operation_type="chat_rag",
            model_name=self._settings.gemini_llm_model,
            estimated_reserve_units=reserve_units,
            request_id=req_id,
            idempotency_key=idempotency_key,
            conversation_id=conv.id if conv is not None else None,
            processing_stage="GENERATING",
            reason="AI assistant chat request",
        )

        # Fast-path idempotent replay if identical idempotency_key already completed
        if reservation.idempotent_replay:
            replay_conv_id = reservation.replay_conversation_id or (conv.id if conv is not None else None)
            if replay_conv_id is not None:
                replay_conv = ConversationService.require_owned_conversation(
                    db,
                    conv_id=replay_conv_id,
                    business_id=ctx.business_id,
                    user_id=ctx.user.id,
                )
                replay_msg = (
                    db.query(AIMessage)
                    .filter(
                        AIMessage.conversation_id == replay_conv.id,
                        AIMessage.business_id == ctx.business_id,
                        AIMessage.user_id == ctx.user.id,
                        AIMessage.role == "assistant",
                        AIMessage.request_id == reservation.request_id,
                    )
                    .order_by(AIMessage.id.desc())
                    .first()
                )
                if replay_msg is None:
                    replay_msg = (
                        db.query(AIMessage)
                        .filter(
                            AIMessage.conversation_id == replay_conv.id,
                            AIMessage.business_id == ctx.business_id,
                            AIMessage.user_id == ctx.user.id,
                            AIMessage.role == "assistant",
                        )
                        .order_by(AIMessage.id.desc())
                        .first()
                    )
                if replay_msg is not None:
                    usage_row = (
                        db.query(AIUsageLog)
                        .filter(AIUsageLog.id == reservation.usage_log_id)
                        .first()
                    )
                    return {
                        "conversation": replay_conv,
                        "assistant_message": replay_msg,
                        "citations": json.loads(replay_msg.sources_json or "[]"),
                        "tools_used": json.loads(replay_msg.tool_calls_json or "[]"),
                        "pending_action": (
                            json.loads(replay_msg.pending_action_json)
                            if replay_msg.pending_action_json
                            else None
                        ),
                        "response_language": replay_msg.language,
                        "request_id": reservation.request_id,
                        "idempotent_replay": True,
                        "credits_used": credits_float(usage_row.credits_consumed_units) if usage_row else 0.0,
                        "credits_reserved": credits_float(usage_row.credits_reserved_units) if usage_row else 0.0,
                        "credits_refunded": credits_float(usage_row.credits_refunded_units) if usage_row else 0.0,
                        "usage_source": usage_row.usage_source if usage_row else "idempotent_replay",
                        "pricing_version": reservation.pricing_version,
                    }

        # Persist conversation and user turn safely now that reservation succeeded (and commit so NO lock stays open)
        if conv is None:
            conv = ConversationService.create_conversation(
                db,
                business_id=ctx.business_id,
                user_id=ctx.user.id,
                preferred_language=preferred_language,
                page_context=page_context,
            )
        else:
            if preferred_language in ("auto", "en", "hi", "mixed") and conv.preferred_language != preferred_language:
                conv.preferred_language = preferred_language
            if page_context:
                conv.last_page_context_json = json.dumps(page_context, ensure_ascii=False)
            db.commit()

        last_msg = (
            db.query(AIMessage)
            .filter(AIMessage.conversation_id == conv.id)
            .order_by(AIMessage.id.desc())
            .first()
        )
        if not (last_msg and last_msg.role == "user" and last_msg.content.strip() == clean_msg):
            ConversationService.append_turn(
                db,
                conv=conv,
                role="user",
                content=clean_msg,
                language=detected_query_lang,
                request_id=req_id,
            )

        # Consult uploaded business docs only for doc/policy queries or when live tools produced no records
        retrieval_res = None
        assembled = None
        gen_res = None
        try:
            if need_rag_docs:
                retrieval_res = self._retrieval.retrieve(
                    db,
                    business_id=ctx.business_id,
                    query=clean_msg,
                    top_k=getattr(self._settings, "ai_retrieval_top_k", 5),
                    min_score=getattr(self._settings, "ai_retrieval_min_score", 0.12),
                    recent_user_context=prev_user,
                    request_id=req_id,
                )

            doc_evidence = retrieval_res.evidence if retrieval_res else []

            # Layer 4: Assemble Natural Grounded Context & Generate Response
            assembled = assemble_grounded_context(
                user_query=clean_msg,
                response_language=effective_lang,
                business_name=ctx.business.name,
                business_type=ctx.business.business_type,
                user_role=ctx.role,
                page_context=page_context,
                conversation_summary=summary_text,
                recent_turns=recent_turns,
                doc_evidence=doc_evidence,
                tool_blocks=tool_blocks,
                answer_mode=intent.answer_mode,
                followup_note=followup_note,
                educational_question=intent.educational_question,
            )

            try:
                gen_res = self._container.llm_service.generate_text(
                    assembled.prompt,
                    system_instruction=assembled.system_instruction,
                    tenant_id=ctx.business_id,
                    conversation_id=conv.id,
                    request_id=req_id,
                )
            except AIServiceError as exc:
                if exc.error_code == AIErrorCode.CONTEXT_LENGTH_EXCEEDED:
                    reduced = assemble_grounded_context(
                        user_query=clean_msg,
                        response_language=effective_lang,
                        business_name=ctx.business.name,
                        business_type=ctx.business.business_type,
                        user_role=ctx.role,
                        page_context=page_context,
                        conversation_summary=None,
                        recent_turns=recent_turns[-2:],
                        doc_evidence=doc_evidence[:2],
                        tool_blocks=tool_blocks[:2],
                        answer_mode=intent.answer_mode,
                        followup_note=followup_note,
                        educational_question=intent.educational_question,
                    )
                    gen_res = self._container.llm_service.generate_text(
                        reduced.prompt,
                        system_instruction=reduced.system_instruction,
                        tenant_id=ctx.business_id,
                        conversation_id=conv.id,
                        request_id=req_id,
                    )
                    assembled = reduced
                else:
                    raise
        except AIServiceError as exc:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            self._container.credit_service.refund_failed_reservation(
                db,
                reservation=reservation,
                error_code=exc.error_code.value,
                error_category=_classify_error_category(exc),
                duration_ms=duration_ms,
                user_id=ctx.user.id,
                conversation_id=conv.id,
                reason=f"100% refund after AI provider failure ({exc.error_code.value})",
            )
            setattr(exc, "conversation_id", conv.id)
            raise
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            self._container.credit_service.refund_failed_reservation(
                db,
                reservation=reservation,
                error_code="INTERNAL_ERROR",
                error_category="internal",
                duration_ms=duration_ms,
                user_id=ctx.user.id,
                conversation_id=conv.id,
                reason=f"100% refund after unexpected AI error ({type(exc).__name__})",
            )
            raise

        assert assembled is not None and gen_res is not None
        # Layer 5: Validate & Sanitize Response (remove leaked enums, phase names, bracket citations on live data)
        valid_doc_indices = [c.citation_index for c in assembled.citations if c.source_kind == "document"]
        val_res = validate_and_sanitize_response(
            gen_res.text,
            allow_document_citations=bool(valid_doc_indices),
            valid_doc_citation_indices=valid_doc_indices,
            reconciled_summary=reconciled_summary,
            expected_skus=expected_skus,
        )
        final_answer_text = val_res.cleaned_text or gen_res.text

        if val_res.warnings:
            log_ai_event(
                self._logger,
                logging.WARNING,
                provider="assistant",
                operation="response_quality_validation",
                status="warnings",
                request_id=req_id,
                tenant_id=ctx.business_id,
                conversation_id=conv.id,
                model=gen_res.model,
                warnings=val_res.warnings,
            )

        # User-facing citations strictly contain uploaded documents (never internal live DB / forecast labels)
        citations_payload = [
            asdict(c) for c in assembled.citations if c.source_kind == "document"
        ]
        total_latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

        assistant_msg = ConversationService.append_turn(
            db,
            conv=conv,
            role="assistant",
            content=final_answer_text,
            language=effective_lang,
            sources=citations_payload,
            tool_calls=executed_tools,
            pending_action=pending_action,
            model_name=gen_res.model,
            prompt_tokens=gen_res.usage.prompt_tokens,
            candidates_tokens=gen_res.usage.candidates_tokens,
            total_tokens=gen_res.usage.total_tokens,
            latency_ms=total_latency_ms,
            request_id=req_id,
            status="COMPLETED",
        )

        # Settle metered cost accurately using provider token counts (or conservative fallback) + unused credit refund
        llm_breakdown = self._container.pricing.calculate_text_generation_cost(
            model_name=gen_res.model,
            prompt_tokens=gen_res.usage.prompt_tokens,
            candidates_tokens=gen_res.usage.candidates_tokens,
            thoughts_tokens=gen_res.usage.thoughts_tokens,
            total_tokens=gen_res.usage.total_tokens,
            prompt_chars=len(assembled.prompt) + len(assembled.system_instruction or ""),
            response_chars=len(final_answer_text),
        )
        embed_units = 0
        embed_tokens = 0
        final_breakdown = llm_breakdown
        if retrieval_res and retrieval_res.metadata.get("embed_executed"):
            emb_breakdown = self._container.pricing.calculate_embedding_batch_cost(
                model_name=retrieval_res.query_embed_model or self._settings.gemini_embedding_model,
                texts=[retrieval_res.query_analysis.focused_query],
                actual_tokens=retrieval_res.query_embed_tokens,
                include_chunk_fee=False,
                operation_type="query_embed",
            )
            embed_units = emb_breakdown.units
            embed_tokens = emb_breakdown.prompt_tokens
            combined_units = llm_breakdown.units + embed_units
            combined_source = (
                llm_breakdown.usage_source
                if emb_breakdown.usage_source == llm_breakdown.usage_source
                else "mixed"
            )
            final_breakdown = CostBreakdown(
                operation_type="chat_rag",
                pricing_version=llm_breakdown.pricing_version,
                model_name=llm_breakdown.model_name,
                prompt_tokens=llm_breakdown.prompt_tokens + embed_tokens,
                candidates_tokens=llm_breakdown.candidates_tokens,
                thoughts_tokens=llm_breakdown.thoughts_tokens,
                total_tokens=llm_breakdown.total_tokens + embed_tokens,
                estimated_tokens=llm_breakdown.estimated_tokens + emb_breakdown.estimated_tokens,
                usage_source=combined_source,
                units=combined_units,
                credits=from_credit_units(combined_units),
            )

        usage_log = self._container.credit_service.capture_usage(
            db,
            reservation=reservation,
            breakdown=final_breakdown,
            duration_ms=total_latency_ms,
            user_id=ctx.user.id,
            conversation_id=conv.id,
            provider_metadata={
                "finish_reason": gen_res.finish_reason,
                "semantic_used": retrieval_res.semantic_used if retrieval_res else False,
                "tool_count": len(executed_tools),
                "primary_intent": intent.primary_intent,
                "quality_warnings": val_res.warnings,
                "thoughts_tokens": gen_res.usage.thoughts_tokens,
                "llm_units": llm_breakdown.units,
                "query_embed_units": embed_units,
                "query_embed_tokens": embed_tokens,
            },
        )

        return {
            "conversation": conv,
            "assistant_message": assistant_msg,
            "citations": citations_payload,
            "tools_used": executed_tools,
            "pending_action": pending_action,
            "response_language": effective_lang,
            "request_id": req_id,
            "idempotent_replay": False,
            "credits_used": credits_float(usage_log.credits_consumed_units),
            "credits_reserved": credits_float(usage_log.credits_reserved_units),
            "credits_refunded": credits_float(usage_log.credits_refunded_units),
            "usage_source": usage_log.usage_source,
            "pricing_version": usage_log.pricing_version,
        }

    @staticmethod
    def confirm_pending_action(
        db: Session,
        ctx: BusinessContext,
        *,
        conv_id: int,
        message_id: int,
        confirm: bool,
    ) -> Dict[str, Any]:
        conv = ConversationService.require_owned_conversation(
            db,
            conv_id=conv_id,
            business_id=ctx.business_id,
            user_id=ctx.user.id,
        )
        msg = (
            db.query(AIMessage)
            .filter(
                AIMessage.id == message_id,
                AIMessage.conversation_id == conv.id,
                AIMessage.business_id == ctx.business_id,
                AIMessage.user_id == ctx.user.id,
            )
            .first()
        )
        if not msg or not msg.pending_action_json:
            raise AIInvalidRequestError("No pending action found on this message.", provider="assistant")

        action = json.loads(msg.pending_action_json)
        if action.get("status") != "PENDING_CONFIRMATION":
            raise AIInvalidRequestError(
                f"Action has already been resolved ({action.get('status')}).",
                provider="assistant",
            )

        if not confirm:
            action["status"] = "CANCELLED"
            msg.pending_action_json = json.dumps(action, ensure_ascii=False)
            db.commit()
            return {"status": "CANCELLED", "action": action}

        if action.get("action_type") == "CREATE_DRAFT_PO":
            result = AuthorizedBusinessTools.execute_confirmed_draft_po(
                db, ctx, action_payload=action["payload"]
            )
            action["status"] = "EXECUTED"
            action["result"] = result
            msg.pending_action_json = json.dumps(action, ensure_ascii=False)
            db.commit()
            return {"status": "EXECUTED", "action": action, "result": result}

        raise AIInvalidRequestError("Unsupported pending action type.", provider="assistant")
