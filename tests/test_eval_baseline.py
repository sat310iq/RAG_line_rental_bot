"""Baseline evaluation regression tests."""

import pytest
from pathlib import Path
import json


def test_eval_results_exist():
    """Test that evaluation results file exists after running eval."""
    results_path = Path(__file__).parent.parent / "data" / "eval" / "eval_results.json"
    
    # This test will pass if results exist, skip if not
    if not results_path.exists():
        pytest.skip("Evaluation results not found. Run 'python scripts/run_eval.py' first.")
    
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    assert 'aggregate_metrics' in data
    assert 'results' in data
    
    metrics = data['aggregate_metrics']
    
    # Check that success rate is above threshold
    success_rate = metrics.get('success_rate', 0)
    assert success_rate >= 0.5, f"Success rate {success_rate} is below 0.5"
    
    # Check that PII leakage rate is below threshold
    pii_leakage_rate = metrics.get('pii_leakage_rate', 1.0)
    assert pii_leakage_rate < 0.1, f"PII leakage rate {pii_leakage_rate} is too high"


def test_eval_questions_exist():
    """Test that evaluation questions file exists."""
    questions_path = Path(__file__).parent.parent / "data" / "eval" / "eval_questions.csv"
    
    assert questions_path.exists(), "Evaluation questions file not found"
    
    # Check that file has content
    with open(questions_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        assert len(lines) > 1, "Evaluation questions file is empty"
