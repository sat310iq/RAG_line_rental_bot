"""Run evaluation on eval dataset."""

import csv
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.tenant_auth import TenantAuth
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer


def calculate_recall_at_k(retrieved_ids: List[str], expected_ids: List[str], k: int) -> float:
    """Calculate Recall@K.
    
    Args:
        retrieved_ids: List of retrieved document IDs
        expected_ids: List of expected document IDs
        k: K value
        
    Returns:
        Recall@K score (0-1)
    """
    if not expected_ids:
        return 0.0
    
    retrieved_top_k = retrieved_ids[:k]
    relevant_retrieved = len(set(retrieved_top_k) & set(expected_ids))
    return relevant_retrieved / len(expected_ids)


def calculate_mrr(retrieved_ids: List[str], expected_ids: List[str]) -> float:
    """Calculate Mean Reciprocal Rank.
    
    Args:
        retrieved_ids: List of retrieved document IDs
        expected_ids: List of expected document IDs
        
    Returns:
        MRR score (0-1)
    """
    if not expected_ids:
        return 0.0
    
    for rank, doc_id in enumerate(retrieved_ids, 1):
        if doc_id in expected_ids:
            return 1.0 / rank
    
    return 0.0


def check_pii_leakage(text: str) -> bool:
    """Check for PII leakage.
    
    Args:
        text: Text to check
        
    Returns:
        True if PII detected, False otherwise
    """
    import re
    patterns = [
        r'\d{1,4}号室',
        r'0\d{1,4}-\d{1,4}-\d{4}',
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',
    ]
    
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    
    return False


def evaluate_question(
    question: str,
    expected_sources: str,
    expected_evidence_ids: str,
    rag_answerer: RAGAnswerer,
    tenant_contract_id: str
) -> Dict[str, Any]:
    """Evaluate a single question.
    
    Args:
        question: Question text
        expected_sources: Expected source types (comma-separated)
        expected_evidence_ids: Expected evidence IDs (comma-separated)
        rag_answerer: RAG answerer instance
        tenant_contract_id: Tenant contract ID
        
    Returns:
        Evaluation metrics dictionary
    """
    start_time = time.time()
    
    try:
        # Get answer
        answer = rag_answerer.answer(question, tenant_contract_id)
        latency = time.time() - start_time
        
        # Extract retrieved document IDs from evidence
        retrieved_ids = []
        for evidence in answer.evidence:
            # Simple extraction (can be improved)
            if 'ID:' in evidence or 'id:' in evidence.lower():
                # Extract ID from evidence string
                import re
                id_matches = re.findall(r'[A-Z]+\d+', evidence)
                retrieved_ids.extend(id_matches)
        
        # Parse expected IDs
        expected_ids = [id.strip() for id in expected_evidence_ids.split()] if expected_evidence_ids else []
        
        # Calculate retrieval metrics
        recall_at_5 = calculate_recall_at_k(retrieved_ids, expected_ids, 5)
        recall_at_10 = calculate_recall_at_k(retrieved_ids, expected_ids, 10)
        mrr = calculate_mrr(retrieved_ids, expected_ids)
        
        # Check PII leakage
        answer_text = f"{answer.conclusion} {answer.next_action} {answer.caveats}"
        pii_leakage = check_pii_leakage(answer_text)
        
        # Check answer completeness (simple check - answer is not empty)
        answer_completeness = 1.0 if answer.conclusion else 0.0
        
        # Check citation accuracy (simple check - evidence list is not empty)
        citation_accuracy = 1.0 if answer.evidence else 0.0
        
        return {
            "question": question,
            "success": True,
            "latency": latency,
            "recall_at_5": recall_at_5,
            "recall_at_10": recall_at_10,
            "mrr": mrr,
            "pii_leakage": pii_leakage,
            "answer_completeness": answer_completeness,
            "citation_accuracy": citation_accuracy,
            "answer": {
                "conclusion": answer.conclusion,
                "evidence": answer.evidence,
                "next_action": answer.next_action,
                "caveats": answer.caveats,
            },
            "retrieved_ids": retrieved_ids,
            "expected_ids": expected_ids,
        }
        
    except Exception as e:
        return {
            "question": question,
            "success": False,
            "error": str(e),
            "latency": time.time() - start_time,
        }


def main():
    """Main evaluation function."""
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Load eval questions
    eval_csv_path = Path(__file__).parent.parent / "data" / "eval" / "eval_questions.csv"
    
    if not eval_csv_path.exists():
        print(f"Eval questions file not found: {eval_csv_path}", file=sys.stderr)
        sys.exit(1)
    
    questions = []
    with open(eval_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            questions.append(row)
    
    print(f"Loaded {len(questions)} evaluation questions")
    
    # Initialize RAG components
    print("Initializing RAG system...")
    tenant_auth = TenantAuth(config)
    # Use first tenant for evaluation
    tenant_contract_id = "CONTRACT001"  # Default for eval
    
    vector_store_manager = VectorStoreManager(config)
    query_cache = QueryCache(config)
    rag_answerer = RAGAnswerer(
        config,
        vector_store_manager,
        query_cache,
        tenant_auth
    )
    
    # Run evaluation
    print("Running evaluation...")
    results = []
    
    for idx, q_data in enumerate(questions, 1):
        print(f"\n[{idx}/{len(questions)}] {q_data['question']}")
        result = evaluate_question(
            q_data['question'],
            q_data.get('expected_sources', ''),
            q_data.get('expected_evidence_ids', ''),
            rag_answerer,
            tenant_contract_id
        )
        results.append(result)
    
    # Calculate aggregate metrics
    successful_results = [r for r in results if r.get('success', False)]
    
    if successful_results:
        avg_latency = sum(r['latency'] for r in successful_results) / len(successful_results)
        avg_recall_at_5 = sum(r.get('recall_at_5', 0) for r in successful_results) / len(successful_results)
        avg_recall_at_10 = sum(r.get('recall_at_10', 0) for r in successful_results) / len(successful_results)
        avg_mrr = sum(r.get('mrr', 0) for r in successful_results) / len(successful_results)
        pii_leakage_rate = sum(1 for r in successful_results if r.get('pii_leakage', False)) / len(successful_results)
        avg_completeness = sum(r.get('answer_completeness', 0) for r in successful_results) / len(successful_results)
        avg_citation_accuracy = sum(r.get('citation_accuracy', 0) for r in successful_results) / len(successful_results)
        
        aggregate_metrics = {
            "total_questions": len(questions),
            "successful_questions": len(successful_results),
            "success_rate": len(successful_results) / len(questions),
            "avg_latency": avg_latency,
            "avg_recall_at_5": avg_recall_at_5,
            "avg_recall_at_10": avg_recall_at_10,
            "avg_mrr": avg_mrr,
            "pii_leakage_rate": pii_leakage_rate,
            "avg_answer_completeness": avg_completeness,
            "avg_citation_accuracy": avg_citation_accuracy,
        }
    else:
        aggregate_metrics = {
            "total_questions": len(questions),
            "successful_questions": 0,
            "success_rate": 0.0,
        }
    
    # Save results
    output_path = Path(__file__).parent.parent / "data" / "eval" / "eval_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    output_data = {
        "aggregate_metrics": aggregate_metrics,
        "results": results,
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print("\n=== Evaluation Complete ===")
    print(f"Results saved to: {output_path}")
    print(f"\nAggregate Metrics:")
    for key, value in aggregate_metrics.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
