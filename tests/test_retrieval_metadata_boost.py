from langchain_core.documents import Document

from src.retrieval_metadata_boost import apply_master_document_boost


def _doc(article: int, *, article_number: str | None = None, content: str | None = None) -> Document:
    return Document(
        page_content=content or f"第{article}条の抜粋",
        metadata={
            "type": "master_txt",
            "doc_kind": "contract",
            "article_seq": article,
            "article_number": article_number or f"第{article}条",
            "filename": "契約書.txt",
        },
    )


def _im_doc(section_id: str, *, content: str | None = None) -> Document:
    return Document(
        page_content=content or f"重要事項第{section_id}節の説明",
        metadata={
            "type": "master_txt",
            "doc_kind": "important_matters",
            "section_id": section_id,
            "filename": "重要事項説明書.txt",
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


def test_jusetsu_section3_query_boosts_section3_to_front() -> None:
    """重説の3項目クエリで section_id==3 の重説 chunk が先頭になること（PR-1a）。"""
    docs = [
        _doc(24),
        _im_doc("5"),
        _im_doc("3", content="月額費用表 家賃31,700円 共益費2,500円"),
    ]
    boosted, trace = apply_master_document_boost(
        "重説の３項目では家賃はいくらですか",
        docs,
        contract_source_q=True,
    )
    assert boosted[0].metadata.get("section_id") == "3"
    reasons = [t.get("boost_reason", "") for t in trace]
    assert any("section_exact:3" in r for r in reasons)


def test_jusetsu_section_boost_not_fired_without_context() -> None:
    """重説文脈なしのクエリでは section boost が発火しないこと。"""
    docs = [_doc(24), _im_doc("3")]
    boosted, trace = apply_master_document_boost(
        "ハザードマップで何か注意点は？",
        docs,
        contract_source_q=True,
    )
    reasons = [t.get("boost_reason", "") for t in trace]
    assert not any("section_exact" in r for r in reasons)
