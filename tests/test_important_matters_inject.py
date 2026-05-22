"""Unit tests for _inject_important_matters_section_if_needed (PR-1b) and
_inject_tokuyaku_penalty_if_needed (PR-1c fix).

Guards G1-G6 / P1-P5 are tested with a mock VectorStoreManager.
No Chroma / OpenAI calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from src.rag_answerer import (
    _inject_important_matters_section_if_needed,
    _inject_tokuyaku_penalty_if_needed,
)


def _contract_doc(article: int = 24) -> Document:
    return Document(
        page_content=f"第{article}条の内容",
        metadata={"doc_kind": "contract", "type": "master_txt"},
    )


def _im_doc(section_id: str = "3") -> Document:
    return Document(
        page_content=f"重要事項§{section_id}の内容",
        metadata={"doc_kind": "important_matters", "section_id": section_id, "type": "master_txt"},
    )


def _vsm(fetch_returns: list[Document] | None = None) -> MagicMock:
    vsm = MagicMock()
    vsm.fetch_master_by_metadata.return_value = fetch_returns if fetch_returns is not None else []
    vsm.fetch_master_by_cite_kind.return_value = []
    return vsm


def _tokuyaku_doc(*, content: str = "特約④（短期解約違約金）6ヶ月以内 114,600円") -> Document:
    return Document(
        page_content=content,
        metadata={"doc_kind": "contract", "cite_kind": "special_terms", "type": "master_txt"},
    )


def _vsm_tokuyaku(fetch_returns: list[Document] | None = None) -> MagicMock:
    vsm = MagicMock()
    vsm.fetch_master_by_metadata.return_value = []
    vsm.fetch_master_by_cite_kind.return_value = fetch_returns if fetch_returns is not None else []
    return vsm


# ---------------------------------------------------------------------------
# G1: skip when neither contract_source_q nor is_important_matters_question
# ---------------------------------------------------------------------------
def test_g1_skips_when_not_contract_source_and_not_imp_matters() -> None:
    docs = [_contract_doc()]
    vsm = _vsm([_im_doc()])
    result, reason = _inject_important_matters_section_if_needed(
        "違約金はいくらですか", docs, vsm, contract_source_q=False, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_metadata.assert_not_called()


def test_g1_passes_for_imp_matters_query_without_contract_source_q() -> None:
    """1-D: G1 relaxed — important_matters query injects even when contract_source_q=False."""
    injected = _im_doc("3")
    docs = [_contract_doc()]
    vsm = _vsm([injected])
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=False, enabled=True
    )
    assert result[0] is injected
    assert reason == "important_matters_section_fetch:sid=3"


# ---------------------------------------------------------------------------
# G5: enabled flag
# ---------------------------------------------------------------------------
def test_g5_skips_when_disabled() -> None:
    docs = [_contract_doc()]
    vsm = _vsm([_im_doc()])
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=True, enabled=False
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_metadata.assert_not_called()


# ---------------------------------------------------------------------------
# G2: is_important_matters_question
# ---------------------------------------------------------------------------
def test_g2_skips_when_not_important_matters_question() -> None:
    docs = [_contract_doc()]
    vsm = _vsm([_im_doc()])
    result, reason = _inject_important_matters_section_if_needed(
        "違約金はいくらですか", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_metadata.assert_not_called()


# ---------------------------------------------------------------------------
# G3: section_id must be extractable
# ---------------------------------------------------------------------------
def test_g3_skips_when_sid_is_none() -> None:
    docs = [_contract_doc()]
    vsm = _vsm([_im_doc()])
    # ハザードマップは important_matters だが sid=None
    result, reason = _inject_important_matters_section_if_needed(
        "ハザードマップで何か注意点は？", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_metadata.assert_not_called()


# ---------------------------------------------------------------------------
# G4: pool must not already have important_matters chunk
# ---------------------------------------------------------------------------
def test_g4_skips_when_pool_already_has_important_matters() -> None:
    docs = [_contract_doc(), _im_doc("3")]
    vsm = _vsm([_im_doc()])
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_metadata.assert_not_called()


# ---------------------------------------------------------------------------
# fetch returns empty → no inject, reason with _empty suffix
# ---------------------------------------------------------------------------
def test_fetch_empty_returns_no_inject_with_reason() -> None:
    docs = [_contract_doc()]
    vsm = _vsm([])
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result is docs
    assert reason is not None and "fetch_empty" in reason and "sid=3" in reason


# ---------------------------------------------------------------------------
# G6: inject fires → chunk prepended, reason logged
# ---------------------------------------------------------------------------
def test_inject_prepends_chunk_when_all_guards_pass() -> None:
    injected_chunk = _im_doc("3")
    docs = [_contract_doc(24)]
    vsm = _vsm([injected_chunk])
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result[0] is injected_chunk
    assert result[1] is docs[0]
    assert reason == "important_matters_section_fetch:sid=3"
    vsm.fetch_master_by_metadata.assert_called_once_with(doc_kind="important_matters", section_id="3")


def test_inject_at_most_one_chunk_even_if_fetch_returns_many() -> None:
    chunks = [_im_doc("3"), _im_doc("3"), _im_doc("3")]
    docs = [_contract_doc()]
    vsm = _vsm(chunks)
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result[0].metadata.get("section_id") == "3"
    assert len(result) == len(docs) + 1  # G6: exactly 1 injected


def test_g4_does_not_block_when_different_section_in_pool() -> None:
    """G4 fix: §1/§20 in pool must not block inject for §3 (was the regression bug)."""
    injected_chunk = _im_doc("3")
    docs = [_contract_doc(24), _im_doc("1"), _im_doc("20")]  # §1 and §20 in pool, NOT §3
    vsm = _vsm([injected_chunk])
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result[0] is injected_chunk
    assert reason == "important_matters_section_fetch:sid=3"


# ---------------------------------------------------------------------------
# _inject_tokuyaku_penalty_if_needed (PR-1c fix)
# ---------------------------------------------------------------------------

def test_tokuyaku_inject_p1_skips_when_not_contract_source() -> None:
    docs = [_contract_doc()]
    vsm = _vsm_tokuyaku([_tokuyaku_doc()])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "違約金はいくらですか？", docs, vsm, contract_source_q=False, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_cite_kind.assert_not_called()


def test_tokuyaku_inject_p4_skips_when_disabled() -> None:
    docs = [_contract_doc()]
    vsm = _vsm_tokuyaku([_tokuyaku_doc()])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "違約金はいくらですか？", docs, vsm, contract_source_q=True, enabled=False
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_cite_kind.assert_not_called()


def test_tokuyaku_inject_p2_skips_when_not_penalty_question() -> None:
    docs = [_contract_doc()]
    vsm = _vsm_tokuyaku([_tokuyaku_doc()])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "特約について教えてください", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_cite_kind.assert_not_called()


def test_tokuyaku_inject_p3_skips_when_penalty_chunk_already_in_pool() -> None:
    penalty = _tokuyaku_doc()
    docs = [penalty]
    vsm = _vsm_tokuyaku([_tokuyaku_doc()])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "違約金はいくらですか？", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_cite_kind.assert_not_called()


def test_tokuyaku_inject_fires_and_prepends_chunk() -> None:
    injected = _tokuyaku_doc()
    docs = [_contract_doc(24)]
    vsm = _vsm_tokuyaku([injected])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "違約金はいくらですか？", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result[0] is injected
    assert result[1] is docs[0]
    assert reason == "tokuyaku_penalty_fetch:special_terms"
    vsm.fetch_master_by_cite_kind.assert_called_once_with(doc_kind="contract", cite_kind="special_terms")


def test_tokuyaku_inject_fires_on_explicit_tokuyaku04_query() -> None:
    injected = _tokuyaku_doc()
    docs = [_contract_doc(26)]
    vsm = _vsm_tokuyaku([injected])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "特約④の短期解約違約金はいくらですか",
        docs,
        vsm,
        contract_source_q=True,
        enabled=True,
    )
    assert result[0] is injected
    assert reason == "tokuyaku_penalty_fetch:special_terms"


def test_tokuyaku_inject_fetch_empty_returns_reason() -> None:
    docs = [_contract_doc(24)]
    vsm = _vsm_tokuyaku([])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "違約金はいくらですか？", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result is docs
    assert reason == "tokuyaku_penalty_fetch_empty"


def test_tokuyaku_inject_filters_non_penalty_chunks_from_fetch() -> None:
    """fetch returns multiple special_terms chunks; only the one with 短期解約違約金 is injected."""
    non_penalty = Document(
        page_content="特約①（水道料の超過分）",
        metadata={"doc_kind": "contract", "cite_kind": "special_terms", "type": "master_txt"},
    )
    penalty = _tokuyaku_doc()
    docs = [_contract_doc(24)]
    vsm = _vsm_tokuyaku([non_penalty, penalty])
    result, reason = _inject_tokuyaku_penalty_if_needed(
        "違約金はいくらですか？", docs, vsm, contract_source_q=True, enabled=True
    )
    assert result[0] is penalty
    assert reason == "tokuyaku_penalty_fetch:special_terms"
