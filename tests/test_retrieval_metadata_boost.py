from langchain_core.documents import Document

from src.retrieval_metadata_boost import apply_master_document_boost


def _doc(article: int, *, article_number: str | None = None, content: str | None = None) -> Document:
    return Document(
        page_content=content or f"第{article}条の抜粋",
        metadata={
            "type": "pdf",
            "doc_kind": "contract",
            "article_seq": article,
            "article_number": article_number or f"第{article}条",
            "filename": "契約書.txt",
        },
    )


def test_usage_purpose_question_infers_article3_boost() -> None:
    docs = [_doc(4), _doc(7), _doc(3, article_number="第3条（使用目的）", content="居住のみを目的として使用する")]
    boosted, trace = apply_master_document_boost(
        "この契約の使用目的は何ですか？",
        docs,
        contract_source_q=True,
    )
    assert boosted[0].metadata.get("article_seq") == 3
    reasons = [t.get("boost_reason", "") for t in trace]
    assert any("usage_purpose_inferred_article:3" in r for r in reasons)


def test_usage_purpose_question_does_not_infer_article3_without_evidence() -> None:
    docs = [_doc(4), _doc(7), _doc(3, article_number="第3条（一般条項）", content="一般条項の説明")]
    boosted, trace = apply_master_document_boost(
        "この契約の使用目的は何ですか？",
        docs,
        contract_source_q=True,
    )
    assert boosted[0].metadata.get("article_seq") == 4
    reasons = [t.get("boost_reason", "") for t in trace]
    assert any("usage_purpose_inference_skipped" in r for r in reasons)
