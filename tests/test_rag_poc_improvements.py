"""Unit tests for eval ID aliases, match_tier, PII split, negative keyword penalties."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from src.eval_id_mapper import EvalIDMapper, _load_eval_aliases_yaml
from src.metrics import (
    analyze_pii,
    calculate_answer_completeness,
    classify_match_tier,
    recall_topk_covers_expected,
)
from src.rag_answerer import AnswerItem, AnswerSchema
from src.rag_answerer import RAGAnswerer


def test_load_eval_aliases_yaml_parses_block(tmp_path: Path) -> None:
    p = tmp_path / "a.yaml"
    p.write_text(
        "aliases:\n  restoration: 契約_原状回復\n  foo: bar\n",
        encoding="utf-8",
    )
    d = _load_eval_aliases_yaml(p)
    assert d["restoration"] == "契約_原状回復"
    assert d["foo"] == "bar"


def test_classify_match_tier() -> None:
    ret = ["a", "b", "c"]
    assert classify_match_tier(ret, ["a"], ["a"], k=5) == "strict_hit"
    assert classify_match_tier(ret, ["x"], ["a"], k=5) == "normalized_only"
    assert classify_match_tier(ret, ["x"], ["y"], k=5) == "miss"


def test_recall_topk_covers_expected() -> None:
    assert recall_topk_covers_expected(["a", "b"], ["a"], 2) is True
    assert recall_topk_covers_expected(["a"], ["a", "b"], 2) is False


def _fa(summary: str) -> AnswerSchema:
    return AnswerSchema(
        items=[AnswerItem(text="x", citation="intent_a")],
        summary=summary,
        evidence=["intent_a"],
        next_action="",
        caveats="",
    )


def test_fact_lookup_completeness_contact_answer_not_penalized() -> None:
    """連絡先案内に「お問い合わせ」「確認」があっても 1.0（狭い vague のみ 0.5）。"""
    s = "水道料金の明細は株式会社To You（管理会社）にお問い合わせください。"
    assert calculate_answer_completeness(_fa(s), "fact_lookup") == 1.0
    s2 = "J:COMカスタマーセンター（097-542-1121）へお問い合わせください。"
    assert calculate_answer_completeness(_fa(s2), "fact_lookup") == 1.0


def test_fact_lookup_completeness_multisentence_not_template_only() -> None:
    """複文で事実＋案内がある場合は逃げ扱いにしない。"""
    s = "駐車場は契約で指定の1台分を利用できます。詳細は管理会社にお問い合わせください。"
    assert calculate_answer_completeness(_fa(s), "fact_lookup") == 1.0


def test_fact_lookup_completeness_explicit_unknown_penalized() -> None:
    assert calculate_answer_completeness(_fa("詳細は不明です。"), "fact_lookup") == 0.5


def test_fact_lookup_completeness_short_no_contact_penalized() -> None:
    assert calculate_answer_completeness(_fa("お問い合わせ"), "fact_lookup") == 0.5


def test_analyze_pii_policy_phone() -> None:
    t = "お問い合わせは 0978-68-1588 まで"
    r = analyze_pii(t)
    assert r["contains_pii"] is True
    assert r["pii_policy_allowed_contact"] is True
    assert r["pii_true_leak_suspected"] is False


def test_analyze_pii_room() -> None:
    r = analyze_pii("101号室の件です")
    assert r["pii_true_leak_suspected"] is True


def test_negative_keyword_penalty_applied() -> None:
    doc = Document(
        page_content="x",
        metadata={
            "intent": "生活_水道請求",
            "keywords": "水道",
            "negative_keywords": "水漏れ|漏水",
            "negative_penalty": "0.35",
        },
    )
    scored = [{"document": doc, "score": 0.9, "source": "deal", "retriever": "vector"}]
    RAGAnswerer._apply_negative_keyword_penalties(MagicMock(), "キッチンから水漏れしています", scored)
    assert scored[0]["score"] == pytest.approx(0.55)


def test_eval_id_mapper_strict_vs_alias(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = MagicMock()
    cfg.get_kb_csv_path.return_value = tmp_path / "empty.csv"
    cfg.get_pdf_documents_dir.return_value = tmp_path
    cfg.get_expected_id_aliases_path.return_value = tmp_path / "aliases.yaml"
    (tmp_path / "aliases.yaml").write_text(
        "aliases:\n  restoration: 契約_原状回復\n",
        encoding="utf-8",
    )

    def _mock_faq(self: EvalIDMapper) -> None:
        self._faq_intents = {"契約_原状回復": "契約_原状回復"}

    def _mock_pdf(self: EvalIDMapper) -> None:
        self._pdf_filename_mapping = {}

    monkeypatch.setattr(EvalIDMapper, "_load_faq_intents", _mock_faq)
    monkeypatch.setattr(EvalIDMapper, "_load_pdf_filename_mapping", _mock_pdf)

    m = EvalIDMapper(cfg)
    assert m.map_expected_id_strict("restoration") == ["restoration"]
    assert m.map_expected_id("restoration") == ["契約_原状回復"]
