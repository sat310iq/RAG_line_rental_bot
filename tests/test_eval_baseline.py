"""Baseline evaluation regression tests."""

import pytest
from pathlib import Path
import json


def test_eval_results_exist():
    """Test that evaluation results file exists and meets QUALITY_GATE thresholds."""
    results_path = Path(__file__).parent.parent / "data" / "eval" / "eval_metrics.json"

    if not results_path.exists():
        pytest.skip("eval_metrics.json not found. Run 'python scripts/run_simple_eval.py --mode full' first.")

    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "aggregate_metrics" in data, "aggregate_metrics key missing"
    metrics = data["aggregate_metrics"]
    assert "total_questions" in metrics, "total_questions key missing"

    # QUALITY_GATE 必須指標（docs/QUALITY_GATE.md と同期）
    hallucination = metrics.get("avg_hallucination_fact_error", 1.0)
    assert hallucination == 0.0, (
        f"hallucination_fact_error {hallucination} must be 0.0 (QUALITY_GATE: block)"
    )

    recall_at_5 = metrics.get("avg_recall_at_5", 0.0)
    assert recall_at_5 >= 0.5, (
        f"avg_recall_at_5 {recall_at_5} is below 0.5 (QUALITY_GATE: target)"
    )

    id_norm = metrics.get("avg_id_normalization_success_rate", 0.0)
    assert id_norm >= 0.9, (
        f"avg_id_normalization_success_rate {id_norm} is below 0.9 (QUALITY_GATE: block)"
    )


def test_eval_questions_exist():
    """Test that evaluation questions file exists."""
    questions_path = Path(__file__).parent.parent / "data" / "eval" / "eval_questions.csv"
    
    assert questions_path.exists(), "Evaluation questions file not found"
    
    # Check that file has content
    with open(questions_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        assert len(lines) > 1, "Evaluation questions file is empty"
