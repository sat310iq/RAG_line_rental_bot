"""Simple evaluation script for RAG system.

This script evaluates the RAG system on a dataset of questions and outputs
results in JSON Lines format.
"""

import argparse
import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.tenant_auth import TenantAuth
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer
from src.evaluate import evaluate_question
from src.opik_integration import OpikIntegration
from src.eval_id_mapper import create_id_mapper
from src.question_typing import QuestionTyper
from src.vector_store_manifest import git_head_short, load_vector_store_manifest
from src.metrics import (
    compute_rag_aggregate_health,
    load_semantic_neighbor_pairs,
    build_semantic_equivalence_map,
)
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_eval_dataset(csv_path: Path) -> List[Dict[str, str]]:
    """Load evaluation dataset from CSV file.
    
    Args:
        csv_path: Path to CSV file
        
    Returns:
        List of question dictionaries
    """
    questions = []
    
    if not csv_path.exists():
        raise FileNotFoundError(f"Evaluation dataset not found: {csv_path}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            questions.append(row)
    
    return questions


def parse_relevant_doc_ids(
    doc_ids_str: str,
    source_type: Optional[str] = None,
    id_mapper=None,
    *,
    strict: bool = False,
) -> List[str]:
    """Parse relevant document IDs from comma-separated string and map to actual IDs.

    Args:
        doc_ids_str: Comma-separated string of document IDs
        source_type: Source type hint (faq, pdf, multi)
        id_mapper: Optional ID mapper instance
        strict: If True, skip eval YAML aliases (strict baseline IDs)

    Returns:
        List of actual document IDs (mapped)
    """
    if not doc_ids_str or doc_ids_str.strip() == "":
        return []

    expected_ids = [id.strip() for id in doc_ids_str.split(",") if id.strip()]

    if id_mapper:
        if strict:
            return id_mapper.map_expected_ids_strict(expected_ids, source_type)
        return id_mapper.map_expected_ids(expected_ids, source_type)

    return expected_ids


def calculate_aggregate_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate aggregate metrics v2 from evaluation results (with question type breakdown).
    
    Args:
        results: List of evaluation results
        
    Returns:
        Dictionary with aggregate metrics v2
    """
    successful_results = [r for r in results if r.get("success", False)]
    
    if not successful_results:
        return {
            "total_questions": len(results),
            "successful_questions": 0,
            "success_rate": 0.0,
        }
    
    total = len(results)
    successful = len(successful_results)
    
    # Overall averages
    metrics = {
        "total_questions": total,
        "successful_questions": successful,
        "success_rate": successful / total if total > 0 else 0.0,
    }
    
    # Retrieval Metrics
    metrics["avg_recall_at_5"] = sum(r.get("recall_at_5", 0.0) or 0.0 for r in successful_results) / successful
    metrics["avg_recall_at_10"] = sum(r.get("recall_at_10", 0.0) or 0.0 for r in successful_results) / successful
    metrics["avg_mrr"] = sum(r.get("mrr", 0.0) or 0.0 for r in successful_results) / successful
    metrics["avg_hit_at_1"] = sum(r.get("hit_at_1", 0.0) or 0.0 for r in successful_results) / successful
    strict_r5 = [r.get("recall_at_5_strict") for r in successful_results if r.get("recall_at_5_strict") is not None]
    if strict_r5:
        metrics["avg_recall_at_5_strict"] = sum(strict_r5) / len(strict_r5)
    match_tiers = [r.get("match_tier") for r in successful_results if r.get("match_tier")]
    if match_tiers:
        metrics["match_tier_strict_hit_rate"] = sum(1 for t in match_tiers if t == "strict_hit") / len(match_tiers)
        metrics["match_tier_normalized_only_rate"] = sum(1 for t in match_tiers if t == "normalized_only") / len(match_tiers)
        metrics["match_tier_miss_rate"] = sum(1 for t in match_tiers if t == "miss") / len(match_tiers)

    # Evaluation Metrics
    id_norm_rates = [r.get("id_normalization_success_rate") for r in successful_results if r.get("id_normalization_success_rate") is not None]
    if id_norm_rates:
        metrics["avg_id_normalization_success_rate"] = sum(id_norm_rates) / len(id_norm_rates)
    
    multi_source_coverages = [r.get("multi_source_coverage") for r in successful_results if r.get("multi_source_coverage") is not None]
    if multi_source_coverages:
        metrics["avg_multi_source_coverage"] = sum(multi_source_coverages) / len(multi_source_coverages)
    
    override_accuracies = [r.get("override_accuracy") for r in successful_results if r.get("override_accuracy") is not None]
    if override_accuracies:
        metrics["avg_override_accuracy"] = sum(override_accuracies) / len(override_accuracies)
    
    pdf_search_rates = [r.get("pdf_search_rate") for r in successful_results if r.get("pdf_search_rate") is not None]
    if pdf_search_rates:
        metrics["avg_pdf_search_rate"] = sum(pdf_search_rates) / len(pdf_search_rates)
    
    # Generation Metrics
    metrics["avg_answer_completeness"] = sum(r.get("answer_completeness", 0.0) for r in successful_results) / successful
    metrics["avg_evidence_binding_rate"] = sum(r.get("evidence_binding_rate", 0.0) for r in successful_results) / successful
    metrics["avg_over_summarization_rate"] = sum(r.get("over_summarization_rate", 0.0) for r in successful_results) / successful
    
    # Safety Metrics
    metrics["avg_relevance"] = sum(r.get("relevance", 0.0) for r in successful_results) / successful
    metrics["avg_hallucination_fact_error"] = sum(r.get("hallucination_fact_error", 0.0) for r in successful_results) / successful
    metrics["avg_hallucination_unsourced_claim"] = sum(r.get("hallucination_unsourced_claim", 0.0) for r in successful_results) / successful
    metrics["avg_hallucination_overreach"] = sum(r.get("hallucination_overreach", 0.0) for r in successful_results) / successful
    metrics["fact_error_rate"] = metrics["avg_hallucination_fact_error"]
    metrics["unsupported_content_rate"] = max(
        metrics["avg_hallucination_unsourced_claim"],
        metrics["avg_hallucination_overreach"],
    )
    metrics["pii_leakage_rate"] = sum(1 for r in successful_results if r.get("contains_pii", False)) / successful
    metrics["pii_true_leak_suspected_rate"] = sum(
        1 for r in successful_results if r.get("pii_true_leak_suspected", False)
    ) / successful
    metrics["pii_policy_allowed_contact_rate"] = sum(
        1 for r in successful_results if r.get("pii_policy_allowed_contact", False)
    ) / successful
    metrics["pii_false_positive_prone_rate"] = sum(
        1 for r in successful_results if r.get("pii_false_positive_prone", False)
    ) / successful
    metrics["semantic_neighbor_hit_rate"] = sum(
        1 for r in successful_results if r.get("semantic_neighbor_hit", False)
    ) / successful
    metrics["match_tier_semantic_rate"] = metrics["semantic_neighbor_hit_rate"]

    compute_rag_aggregate_health(metrics)

    # Prohibited Mention Rate (typed)
    metrics["prohibited_mention_rate"] = sum(1 for r in successful_results if r.get("mentions_prohibited", False)) / successful
    confirmation_results = [r for r in successful_results if r.get("question_type") == "policy_confirmation"]
    if confirmation_results:
        metrics["prohibited_mention_rate.confirmation"] = sum(1 for r in confirmation_results if r.get("mentions_prohibited.confirmation", False)) / len(confirmation_results)
    enumeration_results = [r for r in successful_results if r.get("question_type") == "policy_enumeration"]
    if enumeration_results:
        metrics["prohibited_mention_rate.enumeration"] = sum(1 for r in enumeration_results if r.get("mentions_prohibited.enumeration", False)) / len(enumeration_results)
    
    # Legacy compatibility
    metrics["avg_hallucination"] = 1.0 - max(
        metrics.get("avg_hallucination_fact_error", 0.0),
        metrics.get("avg_hallucination_unsourced_claim", 0.0),
        metrics.get("avg_hallucination_overreach", 0.0)
    )
    
    # Question type breakdown
    type_breakdown = defaultdict(list)
    for r in successful_results:
        q_type = r.get("question_type", "unknown")
        type_breakdown[q_type].append(r)
    
    metrics["by_question_type"] = {}
    for q_type, type_results in type_breakdown.items():
        if type_results:
            type_metrics = {
                "count": len(type_results),
                "avg_recall_at_5": sum(r.get("recall_at_5", 0.0) or 0.0 for r in type_results) / len(type_results),
                "avg_answer_completeness": sum(r.get("answer_completeness", 0.0) for r in type_results) / len(type_results),
                "avg_evidence_binding_rate": sum(r.get("evidence_binding_rate", 0.0) for r in type_results) / len(type_results),
                "avg_relevance": sum(r.get("relevance", 0.0) for r in type_results) / len(type_results),
            }
            metrics["by_question_type"][q_type] = type_metrics

    # Phase 2: template-first UX rate & intent/evidence alignment
    tmpl = [r for r in successful_results if r.get("template_only")]
    metrics["template_only_rate"] = len(tmpl) / successful if successful else 0.0
    aligned = [r for r in successful_results if r.get("intent_aligned")]
    metrics["intent_alignment_rate"] = len(aligned) / successful if successful else 0.0

    # Routing breakdown (AIT-MET-02)
    routing: Dict[str, int] = defaultdict(int)
    for r in successful_results:
        dp = r.get("decision_path") or "unknown"
        # Distinguish 契約ソース RAG from 一般 RAG
        if dp == "rag" and r.get("contract_source_q"):
            routing["contract_source_rag"] += 1
        else:
            routing[dp] += 1
    metrics["routing_breakdown"] = {
        path: {"count": cnt, "rate": round(cnt / successful, 4)}
        for path, cnt in sorted(routing.items())
    }

    # Latency p95 across eval questions (AIT-MET-01)
    latencies = [r["latency_ms"] for r in successful_results if r.get("latency_ms") is not None]
    if latencies:
        sorted_lat = sorted(latencies)
        metrics["latency_p50_ms"] = round(sorted_lat[len(sorted_lat) // 2], 1)
        p95_idx = int(len(sorted_lat) * 0.95)
        metrics["latency_p95_ms"] = round(sorted_lat[p95_idx], 1)
        contract_lats = [
            r["latency_ms"] for r in successful_results
            if r.get("latency_ms") is not None and r.get("contract_source_q")
        ]
        if contract_lats:
            sorted_clat = sorted(contract_lats)
            metrics["contract_rag_latency_p50_ms"] = round(sorted_clat[len(sorted_clat) // 2], 1)
            p95_cidx = int(len(sorted_clat) * 0.95)
            metrics["contract_rag_latency_p95_ms"] = round(sorted_clat[p95_cidx], 1)

    # Latency breakdown: retrieval vs generation (AIT-MET-01)
    retrieval_lats = [r["retrieval_ms"] for r in successful_results if r.get("retrieval_ms") is not None]
    if retrieval_lats:
        sorted_rl = sorted(retrieval_lats)
        metrics["retrieval_ms_p50"] = round(sorted_rl[len(sorted_rl) // 2], 1)
        metrics["retrieval_ms_p95"] = round(sorted_rl[int(len(sorted_rl) * 0.95)], 1)
    generation_lats = [r["generation_ms"] for r in successful_results if r.get("generation_ms") is not None]
    if generation_lats:
        sorted_gl = sorted(generation_lats)
        metrics["generation_ms_p50"] = round(sorted_gl[len(sorted_gl) // 2], 1)
        metrics["generation_ms_p95"] = round(sorted_gl[int(len(sorted_gl) * 0.95)], 1)

    # Input token estimates for contract source RAG (AIT-MET-01)
    contract_toks = [
        r["input_tokens_est"] for r in successful_results
        if r.get("input_tokens_est") and r.get("contract_source_q")
    ]
    if contract_toks:
        sorted_ctoks = sorted(contract_toks)
        metrics["contract_rag_input_tokens_avg"] = round(sum(sorted_ctoks) / len(sorted_ctoks))
        p95_toks_idx = int(len(sorted_ctoks) * 0.95)
        metrics["contract_rag_input_tokens_p95"] = sorted_ctoks[p95_toks_idx]

    # GRAPHRAG-POC-01: multi_hop_coverage aggregate (only questions with expected_graph_nodes)
    mhc_vals = [r.get("multi_hop_coverage") for r in successful_results if r.get("multi_hop_coverage") is not None]
    if mhc_vals:
        metrics["avg_multi_hop_coverage"] = round(sum(mhc_vals) / len(mhc_vals), 4)
        metrics["multi_hop_coverage_n"] = len(mhc_vals)
    graph_expand_counts = [r.get("graph_expand_added", 0) for r in successful_results]
    metrics["graph_expand_fired_rate"] = round(
        sum(1 for c in graph_expand_counts if c > 0) / successful, 4
    ) if successful else 0.0

    # Gates (targets: completeness >= 0.7, miss rate < 0.1)
    ac = metrics.get("avg_answer_completeness", 0.0)
    metrics["completeness_gate_pass"] = bool(ac >= 0.7)
    miss_r = metrics.get("match_tier_miss_rate")
    if miss_r is not None:
        metrics["miss_rate_gate_pass"] = bool(miss_r < 0.1)
    else:
        metrics["miss_rate_gate_pass"] = True
    metrics["generation_kpis_pass"] = bool(
        metrics["completeness_gate_pass"] and metrics.get("miss_rate_gate_pass", True)
    )
    
    return metrics


def _build_eval_run_meta(
    config,
    *,
    eval_mode: str,
    eval_csv_path: Path,
    manifest: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    vs_path = Path(config.rag_vector_store_path)
    if not vs_path.is_absolute():
        vs_path = Path.cwd() / vs_path
    return {
        "run_id": str(uuid.uuid4()),
        "executed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git_head_short(PROJECT_ROOT),
        "eval_mode": eval_mode,
        "eval_csv": str(eval_csv_path),
        "manifest": manifest or {},
        "openai_model": config.openai_model,
        "openai_embedding_model": config.openai_embedding_model,
        "rag_retrieval_k": config.rag_retrieval_k,
        "csv_score_threshold": config.csv_score_threshold,
        "pdf_score_threshold": config.pdf_score_threshold,
    }


def main():
    """Main evaluation function."""
    parser = argparse.ArgumentParser(description="Run RAG evaluation (Metrics v2)")
    parser.add_argument(
        "--mode",
        choices=("full", "smoke"),
        default="full",
        help="full = all questions in eval CSV (default); smoke = fixed small set",
    )
    parser.add_argument(
        "--eval-csv",
        "--questions-file",  # alias used in PoC eval commands
        dest="eval_csv",
        type=Path,
        default=None,
        help="Override path to eval questions CSV",
    )
    parser.add_argument(
        "--output-metrics",
        type=Path,
        default=None,
        help="Override path for output eval_metrics.json (default: data/eval/eval_metrics.json)",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    data_eval = PROJECT_ROOT / "data" / "eval"
    if args.eval_csv is not None:
        eval_csv_path = args.eval_csv if args.eval_csv.is_absolute() else PROJECT_ROOT / args.eval_csv
    elif args.mode == "smoke":
        eval_csv_path = data_eval / "smoke_eval_questions.csv"
    else:
        eval_csv_path = data_eval / "eval_questions.csv"

    try:
        questions = load_eval_dataset(eval_csv_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    vs_path = Path(config.rag_vector_store_path)
    if not vs_path.is_absolute():
        vs_path = Path.cwd() / vs_path
    manifest = load_vector_store_manifest(vs_path)
    eval_run_meta = _build_eval_run_meta(
        config,
        eval_mode=args.mode,
        eval_csv_path=eval_csv_path,
        manifest=manifest,
    )

    print(f"Eval mode: {args.mode}  run_id: {eval_run_meta['run_id']}")
    print(f"Loaded {len(questions)} evaluation questions from {eval_csv_path}")
    
    # Initialize RAG components
    print("Initializing RAG system...")
    tenant_auth = TenantAuth(config)
    vector_store_manager = VectorStoreManager(config)
    query_cache = QueryCache(config)
    # Clear cache for evaluation to ensure fresh results
    query_cache.clear()
    rag_answerer = RAGAnswerer(
        config,
        vector_store_manager,
        query_cache,
        tenant_auth
    )
    
    # Initialize OPIK integration (optional)
    opik = OpikIntegration(config)
    
    # Initialize ID mapper
    id_mapper = create_id_mapper(config)
    
    # Initialize question typer
    question_typer = QuestionTyper(llm_model=config.openai_model)

    semantic_pairs = load_semantic_neighbor_pairs(config.get_semantic_neighbor_classes_path())
    semantic_map = build_semantic_equivalence_map(semantic_pairs)
    pii_allow = config.get_rag_official_contact_pattern_list()
    
    # Run evaluation
    print("\nRunning evaluation (Metrics v2)...")
    print("=" * 80)
    
    results = []
    start_time = time.time()
    
    for idx, q_data in enumerate(questions, 1):
        question = q_data["question"]
        print(f"\n[{idx}/{len(questions)}] {question}")
        
        # Parse question type override from CSV
        question_type_override = None
        if q_data.get("question_type"):
            question_type_str = q_data["question_type"].strip()
            if question_type_str:
                # Validate question type (QuestionType is Literal, so we just use the string)
                valid_types = ["fact_lookup", "procedure", "policy_confirmation", "policy_enumeration", "explanation", "open_ended"]
                if question_type_str in valid_types:
                    question_type_override = question_type_str  # type: ignore
                else:
                    print(f"Warning: Invalid question_type '{question_type_str}', ignoring")
        
        # Parse relevant document IDs and map to actual IDs
        relevant_doc_ids_str = q_data.get("relevant_doc_ids", "") or q_data.get("expected_evidence_ids", "")
        source_type = q_data.get("expected_sources", "").split(",")[0].strip() if q_data.get("expected_sources") else None
        
        # Store original expected IDs (before mapping) for ID normalization check
        original_expected_ids = []
        if relevant_doc_ids_str:
            original_expected_ids = [id.strip() for id in relevant_doc_ids_str.split(",") if id.strip()]
        
        expected_doc_ids = parse_relevant_doc_ids(relevant_doc_ids_str, source_type, id_mapper)
        expected_doc_ids_strict = parse_relevant_doc_ids(
            relevant_doc_ids_str, source_type, id_mapper, strict=True
        )
        
        # Parse expected sources
        expected_sources = None
        if q_data.get("expected_sources"):
            expected_sources = [s.strip() for s in q_data["expected_sources"].split(",") if s.strip()]
        
        # Get expected answer (optional)
        expected_answer = q_data.get("expected_answer", "")
        
        # GRAPHRAG-POC-01: expected graph nodes for multi_hop_coverage
        expected_graph_nodes = q_data.get("expected_graph_nodes", "") or ""

        # Evaluate question (Metrics v2)
        result = evaluate_question(
            question=question,
            expected_doc_ids=expected_doc_ids,
            expected_answer=expected_answer if expected_answer else None,
            rag_answerer=rag_answerer,
            llm_model=config.openai_model,
            tenant_contract_id=None,  # No tenant filtering for evaluation
            question_type_override=question_type_override,
            expected_sources=expected_sources,
            original_expected_ids=original_expected_ids if original_expected_ids else None,
            question_typer=question_typer,
            expected_doc_ids_strict=expected_doc_ids_strict,
            id_mapper=id_mapper,
            pii_extra_allowlist_patterns=pii_allow,
            semantic_equivalence=semantic_map,
            expected_graph_nodes=expected_graph_nodes if expected_graph_nodes else None,
        )
        
        # Add question metadata
        result["question_id"] = f"Q{idx:03d}"
        result["category"] = q_data.get("expected_category", "")
        result["_eval_meta"] = eval_run_meta

        results.append(result)
        
        # Log to Comet if enabled
        opik.log_evaluation_result(result)
        
        # Print quick summary (Metrics v2)
        if result.get("success", False):
            q_type = result.get("question_type", "unknown")
            print(f"  ✓ Type: {q_type}, "
                  f"Recall@5: {result.get('recall_at_5', 0.0) or 0.0:.2f}, "
                  f"Completeness: {result.get('answer_completeness', 0.0):.2f}, "
                  f"Relevance: {result.get('relevance', 0.0):.2f}")
        else:
            print(f"  ✗ Error: {result.get('error', 'Unknown error')}")
    
    elapsed_time = time.time() - start_time
    print("\n" + "=" * 80)
    print(f"Evaluation completed in {elapsed_time:.2f} seconds")
    
    # Calculate aggregate metrics
    aggregate_metrics = calculate_aggregate_metrics(results)
    
    print("\n=== Aggregate Metrics ===")
    for key, value in aggregate_metrics.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")
    
    # Save results to JSON Lines file
    output_path = Path(__file__).parent.parent / "data" / "eval" / "eval_results.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    
    print(f"\nResults saved to: {output_path}")
    
    # Also save aggregate metrics as JSON
    _default_metrics = Path(__file__).parent.parent / "data" / "eval" / "eval_metrics.json"
    metrics_path = args.output_metrics if getattr(args, "output_metrics", None) else _default_metrics
    if not metrics_path.is_absolute():
        metrics_path = Path(__file__).parent.parent / metrics_path
    metrics_data = {
        "aggregate_metrics": aggregate_metrics,
        "evaluation_time_seconds": elapsed_time,
        "total_questions": len(questions),
        "eval_run": eval_run_meta,
    }
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(metrics_data, f, ensure_ascii=False, indent=2)
    
    print(f"Aggregate metrics saved to: {metrics_path}")
    
    if os.environ.get("RAG_EVAL_STRICT"):
        if not aggregate_metrics.get("generation_kpis_pass", True):
            print(
                "\n[RAG_EVAL_STRICT] generation_kpis_pass is false (completeness >= 0.7 and miss rate < 0.1). Exiting 1.",
                file=sys.stderr,
            )
            sys.exit(1)
    
    # Log aggregate metrics to Comet if enabled (this also flushes OPIK items)
    opik.log_aggregate_metrics(aggregate_metrics)
    
    # Close connections
    opik.close()
    
    # Print OPIK experiment info if available
    if hasattr(opik, 'opik_experiment_name') and opik.opik_experiment_name:
        print(f"\nOPIK Experiment: {opik.opik_experiment_name}")
        print(f"OPIK Dataset: {opik.opik_dataset_name}")
        if opik.opik_client:
            try:
                project_url = opik.opik_client.get_project_url(opik.config.comet_project_name)
                print(f"OPIK Project URL: {project_url}")
            except:
                pass


if __name__ == "__main__":
    main()
