"""Generate evaluation report using Decision Hygiene template.

This script generates an evaluation report following the Decision Hygiene standard template.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.decision_rules import DecisionRules, ActionPriority


def load_eval_results(results_path: Path) -> List[Dict[str, Any]]:
    """Load evaluation results from JSON Lines file.
    
    Args:
        results_path: Path to eval_results.jsonl
        
    Returns:
        List of evaluation results
    """
    results = []
    if not results_path.exists():
        return results
    
    with open(results_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    
    return results


def load_aggregate_metrics(metrics_path: Path) -> Dict[str, Any]:
    """Load aggregate metrics from JSON file.
    
    Args:
        metrics_path: Path to eval_metrics.json
        
    Returns:
        Aggregate metrics dictionary
    """
    if not metrics_path.exists():
        return {}
    
    with open(metrics_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get("aggregate_metrics", {})


def generate_report(
    results: List[Dict[str, Any]],
    aggregate_metrics: Dict[str, Any],
    experiment_name: Optional[str] = None,
    dataset_name: Optional[str] = None
) -> str:
    """Generate evaluation report using Decision Hygiene template.
    
    Args:
        results: List of evaluation results
        aggregate_metrics: Aggregate metrics dictionary
        experiment_name: OPIK experiment name (optional)
        dataset_name: OPIK dataset name (optional)
        
    Returns:
        Markdown report string
    """
    # Initialize decision rules
    decision_rules = DecisionRules()
    actions = decision_rules.evaluate(results, aggregate_metrics)
    summary = decision_rules.get_summary()
    
    # Determine high-level decision
    if summary["critical"] > 0:
        decision = "Fix"
        decision_rationale = [
            f"{summary['critical']} critical issue(s) require immediate attention",
            "Evaluation design or fact errors must be fixed before proceeding",
            "Do not modify retrieval until evaluation design is fixed"
        ]
    elif summary["high"] > 0:
        decision = "Fix"
        decision_rationale = [
            f"{summary['high']} high-priority issue(s) need attention",
            "Retrieval or generation improvements required",
            "Monitor progress after fixes"
        ]
    elif summary["medium"] > 0:
        decision = "Monitor"
        decision_rationale = [
            f"{summary['medium']} medium-priority issue(s) to monitor",
            "System is functional but can be improved",
            "Address issues in next iteration"
        ]
    else:
        decision = "Ship"
        decision_rationale = [
            "No critical or high-priority issues detected",
            "System meets quality thresholds",
            "Ready for deployment or next phase"
        ]
    
    # Extract question types
    question_types = set()
    for r in results:
        q_type = r.get("question_type", "unknown")
        if q_type != "unknown":
            question_types.add(q_type)
    
    # Check measurement validity
    id_norm_rate = aggregate_metrics.get("avg_id_normalization_success_rate")
    measurement_valid = id_norm_rate is None or id_norm_rate >= 0.9
    
    # Generate report
    report_lines = [
        "# OPIK Evaluation Report (Decision Hygiene)",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 1. Evaluation Scope",
        "",
        f"- **Experiment**: {experiment_name or 'N/A'}",
        f"- **Dataset**: {dataset_name or 'N/A'}",
        f"- **Question Types**: {', '.join(sorted(question_types)) if question_types else 'unknown'}",
        f"- **Metrics Version**: v2",
        f"- **Total Questions**: {aggregate_metrics.get('total_questions', len(results))}",
        f"- **Successful Questions**: {aggregate_metrics.get('successful_questions', len([r for r in results if r.get('success')]))}",
        "",
        "## 2. High-Level Decision Summary",
        "",
        f"**Decision**: {decision.upper()}",
        "",
        "**Rationale**:",
        ""
    ]
    
    for bullet in decision_rationale:
        report_lines.append(f"- {bullet}")
    
    report_lines.extend([
        "",
        "## 3. Measurement Validity Check",
        "",
        f"- **ID Normalization Success Rate**: {f'{id_norm_rate:.2%}' if id_norm_rate is not None else 'N/A'}",
        f"- **Measurement Valid**: {'✅ Yes' if measurement_valid else '❌ No'}",
        ""
    ])
    
    if not measurement_valid:
        report_lines.extend([
            "⚠️ **Warning**: ID normalization success rate < 0.9. Evaluation design issues detected.",
            "Do NOT modify retrieval until evaluation design is fixed.",
            ""
        ])
    
    # ID Normalization Failures List
    failed_normalizations = [
        {
            "question_id": r.get("question_id", "unknown"),
            "question": r.get("question", "unknown"),
            "original_expected_ids": r.get("original_expected_ids", []),
            "mapped_ids": r.get("expected_doc_ids", []),
            "retrieved_ids": r.get("retrieved_ids", []),
            "normalization_rate": r.get("id_normalization_success_rate", 0.0)
        }
        for r in results
        if r.get("id_normalization_success_rate") is not None
        and r.get("id_normalization_success_rate", 1.0) < 1.0
    ]
    
    if failed_normalizations:
        report_lines.extend([
            "### ID Normalization Failures",
            "",
            "| Question ID | Question | Original IDs | Mapped IDs | Retrieved IDs | Rate |",
            "|-------------|----------|--------------|------------|---------------|------|"
        ])
        for fail in failed_normalizations:
            question_short = fail["question"][:40] + "..." if len(fail["question"]) > 40 else fail["question"]
            original_ids_str = ", ".join(fail["original_expected_ids"][:3])
            if len(fail["original_expected_ids"]) > 3:
                original_ids_str += "..."
            mapped_ids_str = ", ".join(fail["mapped_ids"][:3])
            if len(fail["mapped_ids"]) > 3:
                mapped_ids_str += "..."
            retrieved_ids_str = ", ".join(fail["retrieved_ids"][:3])
            if len(fail["retrieved_ids"]) > 3:
                retrieved_ids_str += "..."
            
            report_lines.append(
                f"| {fail['question_id']} | {question_short} | {original_ids_str} | "
                f"{mapped_ids_str} | {retrieved_ids_str} | {fail['normalization_rate']:.2f} |"
            )
        report_lines.append("")
    
    report_lines.extend([
        "## 4. Metrics by Layer",
        "",
        "### Retrieval Metrics",
        ""
    ])
    
    # Retrieval metrics
    recall_at_5 = aggregate_metrics.get("avg_recall_at_5", 0.0)
    recall_at_10 = aggregate_metrics.get("avg_recall_at_10", 0.0)
    mrr = aggregate_metrics.get("avg_mrr", 0.0)
    hit_at_1 = aggregate_metrics.get("avg_hit_at_1", 0.0)
    
    report_lines.extend([
        f"- **Recall@5**: {recall_at_5:.1%} {'✅' if recall_at_5 >= 0.5 else '❌'}",
        f"- **Recall@10**: {recall_at_10:.1%}",
        f"- **MRR**: {mrr:.3f}",
        f"- **Hit@1**: {hit_at_1:.1%}",
        ""
    ])
    
    # Question type breakdown
    if "by_question_type" in aggregate_metrics:
        report_lines.append("**By Question Type**:")
        for q_type, type_metrics in aggregate_metrics["by_question_type"].items():
            type_recall = type_metrics.get("avg_recall_at_5", 0.0)
            report_lines.append(f"- {q_type}: Recall@5 = {type_recall:.1%}")
        report_lines.append("")
    
    report_lines.extend([
        "### Evaluation Metrics",
        ""
    ])
    
    # Evaluation metrics
    if id_norm_rate is not None:
        report_lines.append(f"- **ID Normalization Success Rate**: {id_norm_rate:.1%} {'✅' if id_norm_rate >= 0.9 else '❌'}")
    multi_source_coverage = aggregate_metrics.get("avg_multi_source_coverage")
    if multi_source_coverage is not None:
        report_lines.append(f"- **Multi-source Coverage**: {multi_source_coverage:.1%}")
    report_lines.append("")
    
    report_lines.extend([
        "### Generation Metrics",
        ""
    ])
    
    # Generation metrics
    completeness = aggregate_metrics.get("avg_answer_completeness", 1.0)
    evidence_binding = aggregate_metrics.get("avg_evidence_binding_rate", 1.0)
    over_summary = aggregate_metrics.get("avg_over_summarization_rate", 0.0)
    
    report_lines.extend([
        f"- **Answer Completeness**: {completeness:.2f} {'✅' if completeness >= 1.0 else '❌'}",
        f"- **Evidence Binding Rate**: {evidence_binding:.1%} {'✅' if evidence_binding >= 0.8 else '❌'}",
        f"- **Over-summarization Rate**: {over_summary:.1%} {'✅' if over_summary < 0.3 else '❌'}",
        ""
    ])
    
    report_lines.extend([
        "### Safety Metrics",
        ""
    ])
    
    # Safety metrics
    relevance = aggregate_metrics.get("avg_relevance", 0.0)
    fact_error = aggregate_metrics.get("avg_hallucination_fact_error", 0.0)
    unsourced_claim = aggregate_metrics.get("avg_hallucination_unsourced_claim", 0.0)
    overreach = aggregate_metrics.get("avg_hallucination_overreach", 0.0)
    pii_rate = aggregate_metrics.get("pii_leakage_rate", 0.0)
    prohibited_rate = aggregate_metrics.get("prohibited_mention_rate", 0.0)
    
    report_lines.extend([
        f"- **Relevance**: {relevance:.1%} {'✅' if relevance >= 0.8 else '❌'}",
        f"- **Hallucination (fact_error)**: {fact_error:.1%} {'✅' if fact_error == 0.0 else '❌ CRITICAL'}",
        f"- **Hallucination (unsourced_claim)**: {unsourced_claim:.1%}",
        f"- **Hallucination (overreach)**: {overreach:.1%}",
        f"- **PII Leakage Rate**: {pii_rate:.1%} {'✅' if pii_rate == 0.0 else '❌'}",
        f"- **Prohibited Mention Rate**: {prohibited_rate:.1%}",
        ""
    ])
    
    # Typed prohibited mention
    if "prohibited_mention_rate.confirmation" in aggregate_metrics:
        report_lines.append(f"- **Prohibited Mention Rate (confirmation)**: {aggregate_metrics['prohibited_mention_rate.confirmation']:.1%}")
    if "prohibited_mention_rate.enumeration" in aggregate_metrics:
        report_lines.append(f"- **Prohibited Mention Rate (enumeration)**: {aggregate_metrics['prohibited_mention_rate.enumeration']:.1%}")
    report_lines.append("")
    
    report_lines.extend([
        "## 5. Noise Diagnosis",
        "",
        "### Measurement Noise",
        "- ID mapping inconsistencies: " + ("Low" if (id_norm_rate is None or id_norm_rate >= 0.9) else "High"),
        "- Question type classification: " + ("Consistent" if question_types else "Inconsistent"),
        "",
        "### Judgment Noise",
        "- LLM evaluation consistency: Check OPIK traces for variance",
        "- Human annotation alignment: N/A (automated evaluation)",
        "",
        "### Data Noise",
        "- Corpus coverage: Check retrieval failures",
        "- Expected answer quality: Review eval_questions.csv",
        "",
        "## 6. Decision Rules Applied",
        ""
    ])
    
    # Decision rules
    if actions:
        report_lines.append("**Triggered Thresholds**:")
        for action in actions:
            priority_marker = "🔴" if action.priority == ActionPriority.CRITICAL else "🟠" if action.priority == ActionPriority.HIGH else "🟡"
            report_lines.append(f"- {priority_marker} **Step {action.step}**: {action.condition}")
            report_lines.append(f"  - Action: {action.action}")
            if action.affected_questions:
                report_lines.append(f"  - Affected: {', '.join(action.affected_questions[:5])}{' ...' if len(action.affected_questions) > 5 else ''}")
        report_lines.append("")
    else:
        report_lines.append("No thresholds triggered. ✅")
        report_lines.append("")
    
    report_lines.extend([
        "## 7. Action Items",
        ""
    ])
    
    # Action items by priority
    critical_actions = [a for a in actions if a.priority == ActionPriority.CRITICAL]
    high_actions = [a for a in actions if a.priority == ActionPriority.HIGH]
    medium_actions = [a for a in actions if a.priority == ActionPriority.MEDIUM]
    low_actions = [a for a in actions if a.priority == ActionPriority.LOW]
    
    if critical_actions:
        report_lines.append("### Fix Now (Critical)")
        for action in critical_actions:
            report_lines.append(f"- **{action.action}**")
            report_lines.append(f"  - Rationale: {action.rationale}")
        report_lines.append("")
    
    if high_actions:
        report_lines.append("### Fix Now (High Priority)")
        for action in high_actions:
            report_lines.append(f"- **{action.action}**")
            report_lines.append(f"  - Rationale: {action.rationale}")
        report_lines.append("")
    
    if medium_actions:
        report_lines.append("### Monitor")
        for action in medium_actions:
            report_lines.append(f"- **{action.action}**")
        report_lines.append("")
    
    if low_actions:
        report_lines.append("### Defer")
        for action in low_actions:
            report_lines.append(f"- **{action.action}**")
        report_lines.append("")
    
    if not actions:
        report_lines.append("No action items. System is performing well. ✅")
        report_lines.append("")
    
    report_lines.extend([
        "## 8. Appendix",
        "",
        "### Links to OPIK Traces",
    ])
    
    if experiment_name:
        report_lines.append(f"- Experiment: `{experiment_name}`")
    if dataset_name:
        report_lines.append(f"- Dataset: `{dataset_name}`")
    
    report_lines.extend([
        "",
        "### Detailed Metrics",
        "",
        "```json",
        json.dumps(aggregate_metrics, ensure_ascii=False, indent=2),
        "```",
        ""
    ])
    
    return "\n".join(report_lines)


def main():
    """Main function."""
    # Paths
    base_path = Path(__file__).parent.parent
    results_path = base_path / "data" / "eval" / "eval_results.jsonl"
    metrics_path = base_path / "data" / "eval" / "eval_metrics.json"
    output_path = base_path / "docs" / "eval" / f"OPIK_EVAL_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    
    # Load data
    print("Loading evaluation results...")
    results = load_eval_results(results_path)
    aggregate_metrics = load_aggregate_metrics(metrics_path)
    
    if not results:
        print(f"Error: No results found in {results_path}", file=sys.stderr)
        sys.exit(1)
    
    # Get experiment/dataset names from metrics if available
    experiment_name = None
    dataset_name = None
    
    # Generate report
    print("Generating report...")
    report = generate_report(results, aggregate_metrics, experiment_name, dataset_name)
    
    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"Report saved to: {output_path}")
    print("\n" + "=" * 80)
    print(report[:2000] + "..." if len(report) > 2000 else report)


if __name__ == "__main__":
    main()
