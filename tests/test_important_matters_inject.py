"""Unit tests for _inject_important_matters_section_if_needed (PR-1b).

Guards G1-G6 are tested with a mock VectorStoreManager.
No Chroma / OpenAI calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from src.rag_answerer import _inject_important_matters_section_if_needed


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
    return vsm


# ---------------------------------------------------------------------------
# G1: contract_source_q must be True
# ---------------------------------------------------------------------------
def test_g1_skips_when_not_contract_source() -> None:
    docs = [_contract_doc()]
    vsm = _vsm([_im_doc()])
    result, reason = _inject_important_matters_section_if_needed(
        "重説の３項目では家賃はいくらですか", docs, vsm, contract_source_q=False, enabled=True
    )
    assert result is docs
    assert reason is None
    vsm.fetch_master_by_metadata.assert_not_called()


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
