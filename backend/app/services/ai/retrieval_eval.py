"""Deterministic retrieval evaluation harness measuring Recall@K, Precision@K, MRR, NDCG@K & latency."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from .retrieval_service import TenantHybridRetrievalService


@dataclass(frozen=True)
class RetrievalEvalCase:
    case_id: str
    query: str
    category: str  # en_doc | hi_doc | mixed_doc | cross_lingual | exact_id | insufficient_evidence
    expected_doc_ids: List[int]
    language: Optional[str] = None


@dataclass(frozen=True)
class RetrievalCaseMetric:
    case_id: str
    category: str
    recall_at_k: float
    precision_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float
    latency_ms: float
    retrieved_doc_ids: List[int]


@dataclass(frozen=True)
class RetrievalEvaluationReport:
    k: int
    total_cases: int
    mean_recall_at_k: float
    mean_precision_at_k: float
    mrr: float
    mean_ndcg_at_k: float
    mean_latency_ms: float
    by_category: Dict[str, Dict[str, float]]
    cases: List[RetrievalCaseMetric]


def evaluate_retrieval_suite(
    db: Session,
    *,
    retrieval_service: TenantHybridRetrievalService,
    business_id: int,
    cases: Sequence[RetrievalEvalCase],
    k: int = 5,
    min_score: float = 0.12,
) -> RetrievalEvaluationReport:
    """Run real queries through TenantHybridRetrievalService and compute IR metrics."""
    metrics: List[RetrievalCaseMetric] = []

    for case in cases:
        res = retrieval_service.retrieve(
            db,
            business_id=business_id,
            query=case.query,
            top_k=k,
            min_score=min_score,
            language=case.language,
        )
        # Rank unique document IDs in retrieved order
        ranked_docs: List[int] = []
        for ev in res.evidence:
            if ev.document_id not in ranked_docs:
                ranked_docs.append(ev.document_id)

        expected = set(case.expected_doc_ids)
        if not expected:
            # Insufficient-evidence check: passes with 1.0 when zero forced irrelevant docs exceed strict threshold
            recall = 1.0 if len(ranked_docs) == 0 else 0.0
            precision = 1.0 if len(ranked_docs) == 0 else 0.0
            rr = 1.0 if len(ranked_docs) == 0 else 0.0
            ndcg = 1.0 if len(ranked_docs) == 0 else 0.0
        else:
            hits = [1 if d in expected else 0 for d in ranked_docs[:k]]
            recall = sum(hits) / len(expected)
            precision = sum(hits) / max(1, min(k, len(ranked_docs))) if ranked_docs else 0.0
            rr = 0.0
            for idx, is_hit in enumerate(hits, start=1):
                if is_hit:
                    rr = 1.0 / idx
                    break
            dcg = sum(hit / math.log2(idx + 2) for idx, hit in enumerate(hits))
            ideal_len = min(k, len(expected))
            idcg = sum(1.0 / math.log2(idx + 2) for idx in range(ideal_len))
            ndcg = dcg / idcg if idcg > 0 else 0.0

        metrics.append(
            RetrievalCaseMetric(
                case_id=case.case_id,
                category=case.category,
                recall_at_k=round(recall, 4),
                precision_at_k=round(precision, 4),
                reciprocal_rank=round(rr, 4),
                ndcg_at_k=round(ndcg, 4),
                latency_ms=res.latency_ms,
                retrieved_doc_ids=ranked_docs,
            )
        )

    n = max(1, len(metrics))
    by_cat: Dict[str, Dict[str, float]] = {}
    cats = sorted({m.category for m in metrics})
    for cat in cats:
        group = [m for m in metrics if m.category == cat]
        gn = len(group)
        by_cat[cat] = {
            "count": float(gn),
            "recall_at_k": round(sum(m.recall_at_k for m in group) / gn, 4),
            "precision_at_k": round(sum(m.precision_at_k for m in group) / gn, 4),
            "mrr": round(sum(m.reciprocal_rank for m in group) / gn, 4),
            "ndcg_at_k": round(sum(m.ndcg_at_k for m in group) / gn, 4),
            "latency_ms": round(sum(m.latency_ms for m in group) / gn, 2),
        }

    return RetrievalEvaluationReport(
        k=k,
        total_cases=len(metrics),
        mean_recall_at_k=round(sum(m.recall_at_k for m in metrics) / n, 4),
        mean_precision_at_k=round(sum(m.precision_at_k for m in metrics) / n, 4),
        mrr=round(sum(m.reciprocal_rank for m in metrics) / n, 4),
        mean_ndcg_at_k=round(sum(m.ndcg_at_k for m in metrics) / n, 4),
        mean_latency_ms=round(sum(m.latency_ms for m in metrics) / n, 2),
        by_category=by_cat,
        cases=metrics,
    )
