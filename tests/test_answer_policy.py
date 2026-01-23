"""Tests for answer policy (structured output, no speculation)."""

import pytest
from pydantic import ValidationError
from src.rag_answerer import AnswerSchema


def test_answer_schema_validation():
    """Test AnswerSchema validation."""
    # Valid schema
    valid_answer = AnswerSchema(
        conclusion="結論です",
        evidence=["証拠1", "証拠2"],
        next_action="次アクション",
        caveats="注意点"
    )
    assert valid_answer.conclusion == "結論です"
    assert len(valid_answer.evidence) == 2
    
    # Invalid schema (missing fields)
    with pytest.raises(ValidationError):
        AnswerSchema(
            conclusion="結論のみ"
            # Missing other fields
        )


def test_answer_schema_no_speculation():
    """Test that answer schema enforces structure (no free-form speculation)."""
    answer = AnswerSchema(
        conclusion="根拠に基づく結論",
        evidence=["doc1", "doc2"],
        next_action="具体的な行動",
        caveats="注意事項"
    )
    
    # All required fields must be present
    assert answer.conclusion
    assert answer.evidence
    assert answer.next_action
    assert answer.caveats
    
    # Evidence should be a list
    assert isinstance(answer.evidence, list)
