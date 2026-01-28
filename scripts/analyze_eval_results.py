"""Analyze evaluation results and provide insights.

This script analyzes evaluation results to identify patterns, issues, and improvement opportunities.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_eval_results(results_path: Path) -> List[Dict[str, Any]]:
    """Load evaluation results from JSONL file.
    
    Args:
        results_path: Path to JSONL file
        
    Returns:
        List of evaluation result dictionaries
    """
    results = []
    with open(results_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def analyze_retrieval_failures(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze retrieval failures (Recall@5 = 0.0).
    
    Args:
        results: List of evaluation results
        
    Returns:
        Analysis dictionary
    """
    failures = []
    for result in results:
        if result.get("recall_at_5", 0.0) == 0.0:
            failures.append({
                "question": result.get("question", ""),
                "expected_ids": result.get("expected_doc_ids", []),
                "retrieved_ids": result.get("retrieved_ids", []),
                "category": result.get("category", ""),
            })
    
    # Group by failure pattern
    patterns = {
        "no_retrieved": [],  # retrieved_ids is empty
        "id_mismatch": [],   # IDs don't match format
        "partial_match": [],  # Some IDs match but not all
    }
    
    for failure in failures:
        if not failure["retrieved_ids"]:
            patterns["no_retrieved"].append(failure)
        elif not set(failure["retrieved_ids"]) & set(failure["expected_ids"]):
            patterns["id_mismatch"].append(failure)
        else:
            patterns["partial_match"].append(failure)
    
    return {
        "total_failures": len(failures),
        "failure_rate": len(failures) / len(results) if results else 0.0,
        "patterns": patterns,
    }


def analyze_hallucination_patterns(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze hallucination patterns.
    
    Args:
        results: List of evaluation results
        
    Returns:
        Analysis dictionary
    """
    high_hallucination = []  # hallucination > 0.7
    low_hallucination = []   # hallucination < 0.3
    
    for result in results:
        if not result.get("success", False):
            continue
        
        hallucination = result.get("hallucination", 0.0)
        recall = result.get("recall_at_5", 0.0)
        
        if hallucination > 0.7:
            high_hallucination.append({
                "question": result.get("question", ""),
                "hallucination": hallucination,
                "recall_at_5": recall,
                "retrieved_ids": result.get("retrieved_ids", []),
                "expected_ids": result.get("expected_doc_ids", []),
            })
        elif hallucination < 0.3:
            low_hallucination.append({
                "question": result.get("question", ""),
                "hallucination": hallucination,
                "recall_at_5": recall,
            })
    
    # Correlation analysis
    correlation_data = []
    for result in results:
        if result.get("success", False):
            correlation_data.append({
                "recall": result.get("recall_at_5", 0.0),
                "hallucination": result.get("hallucination", 0.0),
            })
    
    avg_recall_high_hallucination = (
        sum(r["recall_at_5"] for r in high_hallucination) / len(high_hallucination)
        if high_hallucination else 0.0
    )
    
    return {
        "high_hallucination_count": len(high_hallucination),
        "low_hallucination_count": len(low_hallucination),
        "high_hallucination_examples": high_hallucination[:5],
        "avg_recall_when_high_hallucination": avg_recall_high_hallucination,
        "correlation_insight": (
            "高いハルシネーションは低いRecall@5と相関している可能性があります"
            if avg_recall_high_hallucination < 0.3 else
            "ハルシネーションとRecall@5の相関は弱い可能性があります"
        ),
    }


def generate_improvement_suggestions(analysis: Dict[str, Any]) -> List[str]:
    """Generate improvement suggestions based on analysis.
    
    Args:
        analysis: Analysis results dictionary
        
    Returns:
        List of improvement suggestions
    """
    suggestions = []
    
    retrieval_analysis = analysis.get("retrieval_failures", {})
    hallucination_analysis = analysis.get("hallucination_patterns", {})
    
    # Retrieval suggestions
    if retrieval_analysis.get("failure_rate", 0.0) > 0.5:
        suggestions.append(
            f"検索精度が低い（失敗率: {retrieval_analysis['failure_rate']:.1%}）。"
            "期待IDと実際のIDの形式を確認し、IDマッピングを改善してください。"
        )
    
    no_retrieved_count = len(retrieval_analysis.get("patterns", {}).get("no_retrieved", []))
    if no_retrieved_count > 0:
        suggestions.append(
            f"{no_retrieved_count}件の質問で検索結果が空です。"
            "検索クエリの改善やベクトルストアの再インデックスを検討してください。"
        )
    
    # Hallucination suggestions
    if hallucination_analysis.get("avg_recall_when_high_hallucination", 1.0) < 0.3:
        suggestions.append(
            "高いハルシネーションは低い検索精度と相関しています。"
            "検索精度を向上させることで、ハルシネーションも改善される可能性があります。"
        )
    
    high_hallucination_count = hallucination_analysis.get("high_hallucination_count", 0)
    if high_hallucination_count > 0:
        suggestions.append(
            f"{high_hallucination_count}件の質問でハルシネーションが高いです。"
            "プロンプトの改善や検索結果の品質向上を検討してください。"
        )
    
    return suggestions


def main():
    """Main analysis function."""
    results_path = Path("data/eval/eval_results.jsonl")
    
    if not results_path.exists():
        print(f"Error: Results file not found: {results_path}")
        sys.exit(1)
    
    # Load results
    results = load_eval_results(results_path)
    
    if not results:
        print("No results found.")
        sys.exit(1)
    
    print("=" * 80)
    print("Evaluation Results Analysis")
    print("=" * 80)
    print()
    
    # Overall statistics
    successful = [r for r in results if r.get("success", False)]
    print(f"Total questions: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Success rate: {len(successful) / len(results):.1%}")
    print()
    
    if successful:
        avg_recall = sum(r.get("recall_at_5", 0.0) for r in successful) / len(successful)
        avg_relevance = sum(r.get("relevance", 0.0) for r in successful) / len(successful)
        avg_hallucination = sum(r.get("hallucination", 0.0) for r in successful) / len(successful)
        
        print("Average Metrics:")
        print(f"  Recall@5: {avg_recall:.3f}")
        print(f"  Relevance: {avg_relevance:.3f}")
        print(f"  Hallucination: {avg_hallucination:.3f}")
        print()
    
    # Retrieval failure analysis
    print("=" * 80)
    print("Retrieval Failure Analysis")
    print("=" * 80)
    retrieval_analysis = analyze_retrieval_failures(results)
    print(f"Total failures: {retrieval_analysis['total_failures']}")
    print(f"Failure rate: {retrieval_analysis['failure_rate']:.1%}")
    print()
    
    patterns = retrieval_analysis.get("patterns", {})
    print("Failure patterns:")
    print(f"  No retrieved documents: {len(patterns.get('no_retrieved', []))}")
    print(f"  ID mismatch: {len(patterns.get('id_mismatch', []))}")
    print(f"  Partial match: {len(patterns.get('partial_match', []))}")
    print()
    
    # Hallucination analysis
    print("=" * 80)
    print("Hallucination Pattern Analysis")
    print("=" * 80)
    hallucination_analysis = analyze_hallucination_patterns(results)
    print(f"High hallucination (>0.7): {hallucination_analysis['high_hallucination_count']}")
    print(f"Low hallucination (<0.3): {hallucination_analysis['low_hallucination_count']}")
    print(f"Avg Recall@5 when high hallucination: {hallucination_analysis['avg_recall_when_high_hallucination']:.3f}")
    print(f"Insight: {hallucination_analysis['correlation_insight']}")
    print()
    
    # Improvement suggestions
    print("=" * 80)
    print("Improvement Suggestions")
    print("=" * 80)
    analysis_summary = {
        "retrieval_failures": retrieval_analysis,
        "hallucination_patterns": hallucination_analysis,
    }
    suggestions = generate_improvement_suggestions(analysis_summary)
    
    if suggestions:
        for i, suggestion in enumerate(suggestions, 1):
            print(f"{i}. {suggestion}")
    else:
        print("No specific suggestions. System is performing well!")
    print()
    
    # Save analysis to file
    analysis_path = Path("data/eval/eval_analysis.json")
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    with open(analysis_path, 'w', encoding='utf-8') as f:
        json.dump({
            "summary": {
                "total_questions": len(results),
                "successful": len(successful),
                "success_rate": len(successful) / len(results) if results else 0.0,
            },
            "retrieval_analysis": retrieval_analysis,
            "hallucination_analysis": hallucination_analysis,
            "suggestions": suggestions,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"Analysis saved to: {analysis_path}")


if __name__ == "__main__":
    main()
