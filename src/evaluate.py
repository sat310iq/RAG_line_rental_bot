"""Evaluation logic for RAG system (Metrics v2 with Decision Hygiene).

This module provides the main evaluation function that evaluates a single question
using the RAG pipeline and metrics v2 (Decision Hygiene compliant).
"""

import re
from typing import List, Dict, Any, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from src.eval_id_mapper import EvalIDMapper
from langchain_core.documents import Document
from src.rag_answerer import RAGAnswerer, AnswerSchema
from src.question_typing import QuestionTyper, QuestionType
from src.metrics import (
    calculate_retrieval_metrics_v2,
    calculate_id_normalization_success_rate,
    calculate_multi_source_coverage,
    calculate_override_accuracy,
    calculate_pdf_search_rate,
    calculate_answer_completeness,
    calculate_evidence_binding_rate,
    calculate_over_summarization_rate,
    is_template_only_response,
    compute_intent_alignment,
    llm_evaluate_answer_v2,
    analyze_pii,
    classify_match_tier,
    semantic_neighbor_hit,
    detect_prohibited_policy_v2,
    # Legacy compatibility
    calculate_retrieval_metrics,
    llm_evaluate_answer,
    detect_prohibited_policy,
)


def extract_doc_ids_from_evidence(evidence: List[str]) -> List[str]:
    """Extract document IDs from evidence.
    
    Since RAGAnswerer.answer() now returns actual document IDs in evidence field,
    this function simply returns the evidence list as-is (after removing duplicates).
    
    Args:
        evidence: List of document IDs (from RAGAnswerer.answer().evidence)
        
    Returns:
        List of document IDs (deduplicated)
    """
    # Remove duplicates while preserving order
    seen = set()
    unique_ids = []
    for doc_id in evidence:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            unique_ids.append(doc_id)
    
    return unique_ids


def format_evidence_for_llm(evidence: List[str]) -> str:
    """Format evidence list into a single string for LLM evaluation.
    
    Args:
        evidence: List of evidence strings
        
    Returns:
        Formatted evidence string
    """
    return "\n\n".join([f"[根拠{i+1}]\n{ev}" for i, ev in enumerate(evidence)])


def _compute_multi_hop_coverage(
    pre_rerank_nodes: List[Dict[str, Any]],
    expected_graph_nodes: str,
) -> Optional[float]:
    """Compute fraction of expected graph nodes present in the pre-rerank retrieval pool.

    expected_graph_nodes format: comma-separated specs, each "doc_kind:cite_kind:label_fragment"
    A node is matched if a pool entry has the same doc_kind and cite_kind AND label_fragment
    appears as a substring of cite_label (or cite_label is empty and fragment matches article_number).
    Returns None if expected_graph_nodes is empty.
    """
    if not expected_graph_nodes or not expected_graph_nodes.strip():
        return None
    specs = [s.strip() for s in expected_graph_nodes.split(",") if s.strip()]
    if not specs:
        return None
    hits = 0
    for spec in specs:
        parts = spec.split(":", 2)
        if len(parts) != 3:
            continue
        dk, ck, label_frag = parts
        for node in pre_rerank_nodes:
            if node.get("doc_kind") != dk:
                continue
            if ck and node.get("cite_kind") != ck:
                continue
            cl = node.get("cite_label") or node.get("article_number") or ""
            if label_frag in cl:
                hits += 1
                break
    return hits / len(specs)


def evaluate_question(
    question: str,
    rag_answerer: RAGAnswerer,
    expected_doc_ids: Optional[List[str]] = None,
    expected_answer: Optional[str] = None,
    llm_model: str = "gpt-4o-mini",
    tenant_contract_id: Optional[str] = None,
    question_type_override: Optional[QuestionType] = None,
    expected_sources: Optional[List[str]] = None,
    original_expected_ids: Optional[List[str]] = None,  # For ID normalization check
    question_typer: Optional[QuestionTyper] = None,
    expected_doc_ids_strict: Optional[List[str]] = None,
    id_mapper: Optional["EvalIDMapper"] = None,
    pii_extra_allowlist_patterns: Optional[List[str]] = None,
    semantic_equivalence: Optional[Dict[str, Set[str]]] = None,
    expected_graph_nodes: Optional[str] = None,  # GRAPHRAG-POC-01 multi_hop_coverage
) -> Dict[str, Any]:
    """Evaluate a single question using the RAG pipeline (Metrics v2).
    
    This function:
    1. Classifies question type (LLM + override)
    2. Runs the RAG pipeline to get an answer
    3. Extracts retrieved document IDs from evidence
    4. Calculates retrieval metrics v2 (typed Recall@K, Hit@1)
    5. Calculates evaluation metrics (ID normalization, multi-source coverage)
    6. Calculates generation metrics (completeness, evidence binding, over-summarization)
    7. Evaluates safety metrics v2 (decomposed hallucination, typed prohibited mention)
    8. Checks for PII leakage
    
    Args:
        question: User question
        expected_doc_ids: List of expected document IDs (after ID mapping)
        expected_answer: Expected answer text (optional, for reference)
        rag_answerer: RAG answerer instance
        llm_model: LLM model name for evaluation
        tenant_contract_id: Tenant contract ID (optional)
        question_type_override: Manual question type override from CSV
        expected_sources: List of expected source types (e.g., ["deal", "master"])
        original_expected_ids: Original expected IDs before mapping (for ID normalization check)
        question_typer: QuestionTyper instance (optional, creates new if None)
        expected_doc_ids_strict: Expected IDs without eval YAML aliases (strict recall); if None, uses expected_doc_ids
        pii_extra_allowlist_patterns: Optional extra regex allowlist for published contacts (config-driven).
        semantic_equivalence: Optional id -> equivalent id set map from semantic_neighbor_classes.yaml.

    Returns:
        Dictionary with evaluation metrics v2 and results
    """
    try:
        # 1. Classify question type
        if question_typer is None:
            question_typer = QuestionTyper(llm_model=llm_model)
        
        question_type = question_typer.classify(question, override=question_type_override)
        
        # 2. Run RAG pipeline
        answer: AnswerSchema = rag_answerer.answer(question, tenant_contract_id)
        
        # 3. Extract retrieved document IDs from evidence
        retrieved_ids = extract_doc_ids_from_evidence(answer.evidence)
        
        # 4. Format answer text for evaluation (V2: use render_answer_text)
        from src.rag_answerer import render_answer_text
        answer_text = render_answer_text(answer).strip()
        
        # 5. Format evidence for LLM evaluation
        context_text = format_evidence_for_llm(answer.evidence)
        
        # 6. Retrieval Metrics v2 (normalized = canonical expected_doc_ids)
        strict_ids = expected_doc_ids_strict if expected_doc_ids_strict is not None else (expected_doc_ids or [])
        retrieval_metrics: Dict[str, Any] = {}
        if expected_doc_ids:
            retrieval_metrics = calculate_retrieval_metrics_v2(
                retrieved_ids,
                expected_doc_ids,
                question_type=question_type,
                k_values=[5, 10],
            )
        else:
            retrieval_metrics = {
                "recall_at_5": None,
                "recall_at_10": None,
                "mrr": None,
                "hit_at_1": None,
            }

        retrieval_metrics_strict: Dict[str, Any] = {}
        if strict_ids:
            retrieval_metrics_strict = calculate_retrieval_metrics_v2(
                retrieved_ids,
                strict_ids,
                question_type=question_type,
                k_values=[5, 10],
            )
        if not strict_ids and not (expected_doc_ids or []):
            match_tier = "unknown"
        else:
            match_tier = classify_match_tier(
                retrieved_ids,
                strict_ids,
                expected_doc_ids or [],
                k=5,
            )

        semantic_neighbor_hit_flag = False
        if semantic_equivalence:
            semantic_neighbor_hit_flag = semantic_neighbor_hit(
                retrieved_ids,
                expected_doc_ids or [],
                semantic_equivalence,
            )
        
        # 7. Evaluation Metrics (evaluation design health)
        evaluation_metrics = {}
        if original_expected_ids and expected_doc_ids:
            if id_mapper is not None:
                resolved = sum(
                    1 for oid in original_expected_ids if id_mapper.map_expected_id(oid)
                )
                evaluation_metrics["id_normalization_success_rate"] = (
                    resolved / len(original_expected_ids) if original_expected_ids else 1.0
                )
            else:
                evaluation_metrics["id_normalization_success_rate"] = (
                    calculate_id_normalization_success_rate(
                        original_expected_ids,
                        expected_doc_ids,
                    )
                )
        
        if expected_sources:
            evaluation_metrics["multi_source_coverage"] = calculate_multi_source_coverage(
                retrieved_ids,
                expected_sources
            )
            # Override accuracy (deal should win when expected)
            retrieved_doc_meta = getattr(answer, "retrieved_doc_meta", [])
            evaluation_metrics["override_accuracy"] = calculate_override_accuracy(
                retrieved_doc_meta,
                expected_sources
            )
            evaluation_metrics["pdf_search_rate"] = calculate_pdf_search_rate(
                [doc.get("source_type") for doc in retrieved_doc_meta]
            )
        
        # 8. Generation Metrics
        generation_metrics = {}
        generation_metrics["answer_completeness"] = calculate_answer_completeness(
            answer,  # V2: AnswerSchema directly
            question_type
        )
        
        generation_metrics["evidence_binding_rate"] = calculate_evidence_binding_rate(
            answer,  # V2: AnswerSchema directly
            question_type,
            retrieved_ids
        )
        
        generation_metrics["over_summarization_rate"] = calculate_over_summarization_rate(
            answer_text,
            question_type
        )
        
        # 9. Safety Metrics v2
        safety_metrics = llm_evaluate_answer_v2(
            question=question,
            context=context_text,
            answer=answer_text,
            llm_model=llm_model
        )
        
        # Prohibited mention (typed)
        prohibited_metrics = detect_prohibited_policy_v2(
            answer_text,
            question,
            question_type=question_type
        )
        
        # PII detection (split policy / leak / false-positive prone)
        pii_analysis = analyze_pii(answer_text, pii_extra_allowlist_patterns)
        
        # 10. Compile results
        result = {
            "question": question,
            "question_type": question_type,
            "success": True,
            
            # Retrieval Metrics
            "recall_at_5": retrieval_metrics.get("recall_at_5"),
            "recall_at_10": retrieval_metrics.get("recall_at_10"),
            "mrr": retrieval_metrics.get("mrr"),
            "hit_at_1": retrieval_metrics.get("hit_at_1"),
            **{k: v for k, v in retrieval_metrics.items() if k.startswith("recall_at_") and "." in k},  # Typed recalls
            "recall_at_5_strict": retrieval_metrics_strict.get("recall_at_5"),
            "recall_at_10_strict": retrieval_metrics_strict.get("recall_at_10"),
            "mrr_strict": retrieval_metrics_strict.get("mrr"),
            "hit_at_1_strict": retrieval_metrics_strict.get("hit_at_1"),
            "match_tier": match_tier,
            "semantic_neighbor_hit": semantic_neighbor_hit_flag,
            "expected_doc_ids_strict": strict_ids,
            
            # Evaluation Metrics
            **evaluation_metrics,
            
            # Generation Metrics
            **generation_metrics,
            
            # Safety Metrics
            "relevance": safety_metrics["relevance"],
            "hallucination_fact_error": safety_metrics["hallucination_fact_error"],
            "hallucination_unsourced_claim": safety_metrics["hallucination_unsourced_claim"],
            "hallucination_overreach": safety_metrics["hallucination_overreach"],
            "contains_pii": pii_analysis["contains_pii"],
            "pii_reasons": pii_analysis.get("pii_reasons", []),
            "pii_policy_allowed_contact": pii_analysis.get("pii_policy_allowed_contact", False),
            "pii_true_leak_suspected": pii_analysis.get("pii_true_leak_suspected", False),
            "pii_false_positive_prone": pii_analysis.get("pii_false_positive_prone", False),
            **prohibited_metrics,  # Includes mentions_prohibited and typed versions
            
            # Legacy compatibility (for backward compatibility)
            "hallucination": 1.0 - max(
                safety_metrics["hallucination_fact_error"],
                safety_metrics["hallucination_unsourced_claim"],
                safety_metrics["hallucination_overreach"]
            ),
            
            # Answer details (V2: items and summary)
            "answer": {
                "items": [{"text": item.text, "citation": item.citation} for item in answer.items],
                "summary": answer.summary,
                "next_action": answer.next_action,
                "caveats": answer.caveats,
                "evidence": answer.evidence,
            },
            "answer_text": answer_text,
            "retrieved_ids": retrieved_ids,
            "expected_doc_ids": expected_doc_ids or [],
            "expected_answer": expected_answer,
            # Generation quality aux (Phase 2)
            "template_only": is_template_only_response(answer.summary or ""),
            "intent_aligned": compute_intent_alignment(answer),
            # Routing observability (AIT-MET-01/02)
            "decision_path": getattr(answer, "decision_path", None),
            "latency_ms": getattr(answer, "latency_ms", None),
            "retrieval_ms": getattr(answer, "retrieval_ms", None),
            "generation_ms": getattr(answer, "generation_ms", None),
            "contract_source_q": bool(getattr(answer, "contract_source_q", False)),
            "input_tokens_est": (
                (getattr(answer, "search_debug_info", None) or {}).get("llm_evidence_token_estimate", 0)
                + max(1, len(question) // 4)
            ),
        }
        # GRAPHRAG-POC-01: multi_hop_coverage from pre-rerank pool
        _sdi = getattr(answer, "search_debug_info", None) or {}
        _pre_rerank = _sdi.get("pre_rerank_nodes") or []
        _graph_expand_added = _sdi.get("graph_expand_added", 0)
        result["graph_expand_added"] = _graph_expand_added
        mhc = _compute_multi_hop_coverage(_pre_rerank, expected_graph_nodes or "")
        if mhc is not None:
            result["multi_hop_coverage"] = mhc
        return result
        
    except Exception as e:
        import sys
        print(f"Error in evaluate_question: {e}", file=sys.stderr)
        return {
            "question": question,
            "question_type": question_type_override or "open_ended",
            "success": False,
            "error": str(e),
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr": 0.0,
            "hit_at_1": 0.0,
            "relevance": 0.0,
            "hallucination": 0.0,
            "hallucination_fact_error": 0.0,
            "hallucination_unsourced_claim": 0.0,
            "hallucination_overreach": 0.0,
            "contains_pii": False,
            "pii_reasons": [],
            "pii_policy_allowed_contact": False,
            "pii_true_leak_suspected": False,
            "pii_false_positive_prone": False,
            "match_tier": "unknown",
            "semantic_neighbor_hit": False,
            "mentions_prohibited": False,
            "answer_completeness": 0.0,
            "evidence_binding_rate": 0.0,
            "over_summarization_rate": 0.0,
            "template_only": False,
            "intent_aligned": False,
        }
