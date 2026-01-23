"""Analyze evaluation results and generate visualizations.

Supports both JSON and JSON Lines format for backward compatibility.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict

try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    import numpy as np
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    print("Warning: matplotlib/seaborn not available. Visualization will be skipped.")


def load_results(results_path: Path) -> List[Dict[str, Any]]:
    """Load evaluation results from JSON or JSON Lines file.
    
    Args:
        results_path: Path to results file
        
    Returns:
        List of evaluation result dictionaries
    """
    results = []
    
    if not results_path.exists():
        raise FileNotFoundError(f"Results file not found: {results_path}")
    
    # Try JSON Lines format first (new format)
    if results_path.suffix == '.jsonl':
        with open(results_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
    else:
        # Try JSON format (old format)
        with open(results_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'results' in data:
                results = data['results']
            elif isinstance(data, list):
                results = data
    
    return results


def analyze_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze evaluation results.
    
    Args:
        results: List of evaluation result dictionaries
        
    Returns:
        Analysis dictionary
    """
    successful_results = [r for r in results if r.get('success', False)]
    failed_results = [r for r in results if not r.get('success', False)]
    
    analysis = {
        "total": len(results),
        "successful": len(successful_results),
        "failed": len(failed_results),
        "success_rate": len(successful_results) / len(results) if results else 0.0,
    }
    
    if successful_results:
        # Latency analysis (if available)
        if 'latency' in successful_results[0]:
            latencies = [r.get('latency', 0) for r in successful_results]
            analysis["latency"] = {
                "mean": sum(latencies) / len(latencies),
                "min": min(latencies),
                "max": max(latencies),
                "median": sorted(latencies)[len(latencies) // 2],
            }
        
        # Recall analysis
        recall_at_5_scores = [r.get('recall_at_5', 0) for r in successful_results]
        recall_at_10_scores = [r.get('recall_at_10', 0) for r in successful_results]
        analysis["recall"] = {
            "mean_recall_at_5": sum(recall_at_5_scores) / len(recall_at_5_scores),
            "mean_recall_at_10": sum(recall_at_10_scores) / len(recall_at_10_scores),
        }
        
        # MRR analysis
        mrr_scores = [r.get('mrr', 0) for r in successful_results]
        analysis["mrr"] = {
            "mean": sum(mrr_scores) / len(mrr_scores),
        }
        
        # LLM evaluation metrics (if available)
        if 'relevance' in successful_results[0]:
            relevance_scores = [r.get('relevance', 0) for r in successful_results]
            hallucination_scores = [r.get('hallucination', 0) for r in successful_results]
            analysis["llm_metrics"] = {
                "mean_relevance": sum(relevance_scores) / len(relevance_scores),
                "mean_hallucination": sum(hallucination_scores) / len(hallucination_scores),
            }
        
        # PII leakage analysis
        pii_leakage_count = sum(1 for r in successful_results if r.get('contains_pii', False) or r.get('pii_leakage', False))
        analysis["pii_leakage"] = {
            "count": pii_leakage_count,
            "rate": pii_leakage_count / len(successful_results),
        }
        
        # Prohibited policy mention analysis (if available)
        if 'mentions_prohibited' in successful_results[0]:
            prohibited_count = sum(1 for r in successful_results if r.get('mentions_prohibited', False))
            analysis["prohibited_mention"] = {
                "count": prohibited_count,
                "rate": prohibited_count / len(successful_results),
            }
        
        # Category-based analysis (if available)
        category_stats = defaultdict(lambda: {"count": 0, "scores": []})
        for r in successful_results:
            category = r.get('category', 'unknown')
            category_stats[category]["count"] += 1
            category_stats[category]["scores"].append({
                "recall_at_5": r.get('recall_at_5', 0),
                "recall_at_10": r.get('recall_at_10', 0),
                "mrr": r.get('mrr', 0),
                "relevance": r.get('relevance', 0),
                "hallucination": r.get('hallucination', 0),
            })
        
        if len(category_stats) > 1:
            analysis["by_category"] = {}
            for category, stats in category_stats.items():
                scores = stats["scores"]
                analysis["by_category"][category] = {
                    "count": stats["count"],
                    "avg_recall_at_5": sum(s["recall_at_5"] for s in scores) / len(scores),
                    "avg_recall_at_10": sum(s["recall_at_10"] for s in scores) / len(scores),
                    "avg_mrr": sum(s["mrr"] for s in scores) / len(scores),
                    "avg_relevance": sum(s["relevance"] for s in scores) / len(scores) if scores[0].get("relevance") else None,
                    "avg_hallucination": sum(s["hallucination"] for s in scores) / len(scores) if scores[0].get("hallucination") else None,
                }
        
        # Low score questions
        low_score_threshold = 0.5
        low_score_questions = [
            r for r in successful_results
            if r.get('recall_at_5', 0) < low_score_threshold or r.get('relevance', 1.0) < low_score_threshold
        ]
        analysis["low_score_questions"] = [
            {
                "question": r['question'],
                "recall_at_5": r.get('recall_at_5', 0),
                "recall_at_10": r.get('recall_at_10', 0),
                "mrr": r.get('mrr', 0),
                "relevance": r.get('relevance', 0),
                "hallucination": r.get('hallucination', 0),
            }
            for r in low_score_questions
        ]
    
    if failed_results:
        analysis["errors"] = [
            {
                "question": r['question'],
                "error": r.get('error', 'Unknown error'),
            }
            for r in failed_results
        ]
    
    return analysis


def create_visualizations(results: List[Dict[str, Any]], output_dir: Path) -> None:
    """Create visualization plots.
    
    Args:
        results: List of evaluation result dictionaries
        output_dir: Output directory for plots
    """
    if not VISUALIZATION_AVAILABLE:
        return
    
    successful_results = [r for r in results if r.get('success', False)]
    
    if not successful_results:
        print("No successful results to visualize.")
        return
    
    # Set style
    sns.set_style("whitegrid")
    
    # 1. Latency distribution
    latencies = [r['latency'] for r in successful_results]
    plt.figure(figsize=(10, 6))
    plt.hist(latencies, bins=20, edgecolor='black')
    plt.xlabel('Latency (seconds)')
    plt.ylabel('Frequency')
    plt.title('Query Latency Distribution')
    plt.savefig(output_dir / "latency_distribution.png")
    plt.close()
    
    # 2. Recall scores
    recall_at_5_scores = [r.get('recall_at_5', 0) for r in successful_results]
    recall_at_10_scores = [r.get('recall_at_10', 0) for r in successful_results]
    
    plt.figure(figsize=(10, 6))
    x = range(len(successful_results))
    plt.plot(x, recall_at_5_scores, label='Recall@5', marker='o')
    plt.plot(x, recall_at_10_scores, label='Recall@10', marker='s')
    plt.xlabel('Question Index')
    plt.ylabel('Recall Score')
    plt.title('Recall Scores by Question')
    plt.legend()
    plt.ylim(0, 1)
    plt.savefig(output_dir / "recall_scores.png")
    plt.close()
    
    # 3. MRR scores
    mrr_scores = [r.get('mrr', 0) for r in successful_results]
    plt.figure(figsize=(10, 6))
    plt.bar(range(len(mrr_scores)), mrr_scores)
    plt.xlabel('Question Index')
    plt.ylabel('MRR Score')
    plt.title('Mean Reciprocal Rank by Question')
    plt.ylim(0, 1)
    plt.savefig(output_dir / "mrr_scores.png")
    plt.close()
    
    print(f"Visualizations saved to {output_dir}")


def main():
    """Main analysis function."""
    # Try to load results from JSON Lines (new format) or JSON (old format)
    eval_dir = Path(__file__).parent.parent / "data" / "eval"
    results_path_jsonl = eval_dir / "eval_results.jsonl"
    results_path_json = eval_dir / "eval_results.json"
    
    results = []
    aggregate_metrics = {}
    
    # Try JSON Lines first (new format)
    if results_path_jsonl.exists():
        print(f"Loading results from: {results_path_jsonl}")
        results = load_results(results_path_jsonl)
        # Try to load aggregate metrics from separate file
        metrics_path = eval_dir / "eval_metrics.json"
        if metrics_path.exists():
            with open(metrics_path, 'r', encoding='utf-8') as f:
                metrics_data = json.load(f)
                aggregate_metrics = metrics_data.get('aggregate_metrics', {})
    elif results_path_json.exists():
        print(f"Loading results from: {results_path_json}")
        with open(results_path_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        results = data.get('results', [])
        aggregate_metrics = data.get('aggregate_metrics', {})
    else:
        print(f"Results file not found: {results_path_jsonl} or {results_path_json}", file=sys.stderr)
        print("Please run 'python scripts/run_simple_eval.py' first.", file=sys.stderr)
        sys.exit(1)
    
    print("=== Evaluation Results Analysis ===")
    print()
    
    # Print aggregate metrics
    print("Aggregate Metrics:")
    for key, value in aggregate_metrics.items():
        print(f"  {key}: {value}")
    print()
    
    # Analyze results
    analysis = analyze_results(results)
    
    print("Detailed Analysis:")
    print(f"  Total questions: {analysis['total']}")
    print(f"  Successful: {analysis['successful']}")
    print(f"  Failed: {analysis['failed']}")
    print(f"  Success rate: {analysis['success_rate']:.2%}")
    print()
    
    if 'latency' in analysis:
        print("Latency:")
        for key, value in analysis['latency'].items():
            print(f"  {key}: {value:.3f}s")
        print()
    
    if 'recall' in analysis:
        print("Recall:")
        for key, value in analysis['recall'].items():
            print(f"  {key}: {value:.3f}")
        print()
    
    if 'mrr' in analysis:
        print("MRR:")
        print(f"  mean: {analysis['mrr']['mean']:.3f}")
        print()
    
    if 'llm_metrics' in analysis:
        print("LLM Evaluation Metrics:")
        print(f"  mean_relevance: {analysis['llm_metrics']['mean_relevance']:.3f}")
        print(f"  mean_hallucination: {analysis['llm_metrics']['mean_hallucination']:.3f}")
        print()
    
    if 'pii_leakage' in analysis:
        print("PII Leakage:")
        print(f"  count: {analysis['pii_leakage']['count']}")
        print(f"  rate: {analysis['pii_leakage']['rate']:.2%}")
        print()
    
    if 'prohibited_mention' in analysis:
        print("Prohibited Policy Mention:")
        print(f"  count: {analysis['prohibited_mention']['count']}")
        print(f"  rate: {analysis['prohibited_mention']['rate']:.2%}")
        print()
    
    if 'by_category' in analysis:
        print("Metrics by Category:")
        for category, stats in analysis['by_category'].items():
            print(f"  {category}:")
            print(f"    count: {stats['count']}")
            print(f"    avg_recall_at_5: {stats['avg_recall_at_5']:.3f}")
            print(f"    avg_relevance: {stats['avg_relevance']:.3f}" if stats['avg_relevance'] is not None else "    avg_relevance: N/A")
            print()
    
    if 'low_score_questions' in analysis and analysis['low_score_questions']:
        print("Low Score Questions (Recall@5 < 0.5 or Relevance < 0.5):")
        for q in analysis['low_score_questions']:
            print(f"  - {q['question']}")
            print(f"    Recall@5: {q['recall_at_5']:.3f}, Recall@10: {q['recall_at_10']:.3f}, MRR: {q['mrr']:.3f}")
            if q.get('relevance') is not None:
                print(f"    Relevance: {q['relevance']:.3f}, Hallucination: {q['hallucination']:.3f}")
        print()
    
    if 'errors' in analysis and analysis['errors']:
        print("Failed Questions:")
        for err in analysis['errors']:
            print(f"  - {err['question']}")
            print(f"    Error: {err['error']}")
        print()
    
    # Create visualizations
    output_dir = Path(__file__).parent.parent / "data" / "eval" / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if VISUALIZATION_AVAILABLE:
        print("Creating visualizations...")
        create_visualizations(results, output_dir)
    else:
        print("Skipping visualizations (matplotlib/seaborn not available)")


if __name__ == "__main__":
    main()
