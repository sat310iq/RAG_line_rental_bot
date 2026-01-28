"""Simple evaluation script for RAG system.

This script evaluates the RAG system on a dataset of questions and outputs
results in JSON Lines format.
"""

import csv
import json
import sys
import time
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


def parse_relevant_doc_ids(doc_ids_str: str, source_type: Optional[str] = None, id_mapper = None) -> List[str]:
    """Parse relevant document IDs from comma-separated string and map to actual IDs.
    
    Args:
        doc_ids_str: Comma-separated string of document IDs
        source_type: Source type hint (faq, ops, pdf, multi)
        id_mapper: Optional ID mapper instance
        
    Returns:
        List of actual document IDs (mapped)
    """
    if not doc_ids_str or doc_ids_str.strip() == "":
        return []
    
    # Split by comma and strip whitespace
    expected_ids = [id.strip() for id in doc_ids_str.split(",") if id.strip()]
    
    # Map to actual IDs if mapper is provided
    if id_mapper:
        return id_mapper.map_expected_ids(expected_ids, source_type)
    
    return expected_ids


def calculate_aggregate_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate aggregate metrics from evaluation results.
    
    Args:
        results: List of evaluation results
        
    Returns:
        Dictionary with aggregate metrics
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
    
    # Calculate averages
    avg_recall_at_5 = sum(r.get("recall_at_5", 0.0) for r in successful_results) / successful
    avg_recall_at_10 = sum(r.get("recall_at_10", 0.0) for r in successful_results) / successful
    avg_mrr = sum(r.get("mrr", 0.0) for r in successful_results) / successful
    avg_relevance = sum(r.get("relevance", 0.0) for r in successful_results) / successful
    avg_hallucination = sum(r.get("hallucination", 0.0) for r in successful_results) / successful
    
    # Calculate rates
    pii_leakage_rate = sum(1 for r in successful_results if r.get("contains_pii", False)) / successful
    prohibited_mention_rate = sum(1 for r in successful_results if r.get("mentions_prohibited", False)) / successful
    
    return {
        "total_questions": total,
        "successful_questions": successful,
        "success_rate": successful / total if total > 0 else 0.0,
        "avg_recall_at_5": avg_recall_at_5,
        "avg_recall_at_10": avg_recall_at_10,
        "avg_mrr": avg_mrr,
        "avg_relevance": avg_relevance,
        "avg_hallucination": avg_hallucination,
        "pii_leakage_rate": pii_leakage_rate,
        "prohibited_mention_rate": prohibited_mention_rate,
    }


def main():
    """Main evaluation function."""
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Load evaluation dataset
    eval_csv_path = Path(__file__).parent.parent / "data" / "eval" / "eval_questions.csv"
    
    try:
        questions = load_eval_dataset(eval_csv_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Loaded {len(questions)} evaluation questions")
    
    # Limit to first 10 questions for testing
    if len(questions) > 10:
        print(f"⚠️  Testing mode: Limiting to first 10 questions")
        questions = questions[:10]
    
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
    
    # Run evaluation
    print("\nRunning evaluation...")
    print("=" * 80)
    
    results = []
    start_time = time.time()
    
    for idx, q_data in enumerate(questions, 1):
        question = q_data["question"]
        print(f"\n[{idx}/{len(questions)}] {question}")
        
        # Parse relevant document IDs and map to actual IDs
        relevant_doc_ids_str = q_data.get("relevant_doc_ids", "") or q_data.get("expected_evidence_ids", "")
        source_type = q_data.get("expected_sources", "").split(",")[0].strip() if q_data.get("expected_sources") else None
        expected_doc_ids = parse_relevant_doc_ids(relevant_doc_ids_str, source_type, id_mapper)
        
        # Get expected answer (optional)
        expected_answer = q_data.get("expected_answer", "")
        
        # Evaluate question
        result = evaluate_question(
            question=question,
            expected_doc_ids=expected_doc_ids,
            expected_answer=expected_answer if expected_answer else None,
            rag_answerer=rag_answerer,
            llm_model=config.openai_model,
            tenant_contract_id=None  # No tenant filtering for evaluation
        )
        
        # Add question metadata
        result["question_id"] = f"Q{idx:03d}"
        result["category"] = q_data.get("expected_category", "")
        
        results.append(result)
        
        # Log to Comet if enabled
        opik.log_evaluation_result(result)
        
        # Print quick summary
        if result.get("success", False):
            print(f"  ✓ Recall@5: {result.get('recall_at_5', 0.0):.2f}, "
                  f"Relevance: {result.get('relevance', 0.0):.2f}, "
                  f"Hallucination: {result.get('hallucination', 0.0):.2f}")
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
    metrics_path = Path(__file__).parent.parent / "data" / "eval" / "eval_metrics.json"
    metrics_data = {
        "aggregate_metrics": aggregate_metrics,
        "evaluation_time_seconds": elapsed_time,
        "total_questions": len(questions),
    }
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(metrics_data, f, ensure_ascii=False, indent=2)
    
    print(f"Aggregate metrics saved to: {metrics_path}")
    
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
