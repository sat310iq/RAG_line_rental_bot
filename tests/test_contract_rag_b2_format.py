"""B2 contract RAG display: PDF template, not low-relevance path."""

from langchain_core.documents import Document

from src.rag_answerer import AnswerItem, AnswerSchema, render_answer_text
from src.contract_rag_format import (
    B2_HEADING_CAVEAT,
    B2_HEADING_NEXT,
    B2_HEADING_SOURCE,
    B2_HEADING_SUMMARY,
    DISPLAY_FORMAT_B2,
    build_source_reference,
    build_source_reference_line,
    format_b2_contract_rag_display,
    uses_master_pdf_docs,
)


def _pdf_doc(
    filename: str = "master.pdf",
    page: int = 3,
    *,
    article_seq: int | None = 10,
    paragraph_seq: int | None = None,
    paragraph_conf: str | None = None,
    cite_label: str | None = None,
    doc_kind: str | None = "contract",
) -> Document:
    meta: dict = {
        "type": "pdf",
        "filename": filename,
        "page": page,
        "doc_kind": doc_kind,
        "article_seq": article_seq,
        "article_number": f"第{article_seq}条" if article_seq is not None else None,
    }
    if paragraph_seq is not None:
        meta["paragraph_seq"] = paragraph_seq
        meta["paragraph_seq_confidence"] = paragraph_conf or "inferred"
    if cite_label:
        meta["cite_label"] = cite_label
    return Document(page_content="契約条項の抜粋…", metadata=meta)


def _kb_faq_doc() -> Document:
    return Document(
        page_content="FAQ回答",
        metadata={"type": "kb_faq", "intent": "契約_水道光熱費"},
    )


def test_uses_master_pdf_docs_true_when_pdf():
    assert uses_master_pdf_docs([_pdf_doc()]) is True
    assert uses_master_pdf_docs([_kb_faq_doc(), _pdf_doc()]) is True


def test_uses_master_pdf_docs_false_kb_only():
    assert uses_master_pdf_docs([_kb_faq_doc()]) is False
    assert uses_master_pdf_docs([]) is False


def test_build_source_reference_includes_filename_and_page():
    ref = build_source_reference([_pdf_doc("基本契約.pdf", page=2, article_seq=8)])
    assert "基本契約.pdf" in ref
    assert "p.2" in ref
    assert "第8条" in ref


def test_build_source_reference_article_paragraph_when_confident():
    ref = build_source_reference_line(
        _pdf_doc(
            "基本契約.pdf",
            page=1,
            article_seq=4,
            paragraph_seq=2,
            paragraph_conf="inferred",
        ).metadata
    )
    assert "第4条第2項" in ref


def test_build_source_reference_no_fake_article_from_preamble_label():
    ref = build_source_reference_line(
        {
            "type": "pdf",
            "filename": "契約.txt",
            "page": 2,
            "doc_kind": "contract",
            "article_seq": None,
            "article_number": None,
            "cite_label": "別表第1（第17条関係）",
        }
    )
    assert "第（前文" not in ref
    assert "別表第1" in ref


def test_build_source_reference_legacy_article_number_string():
    ref = build_source_reference_line(
        {
            "type": "pdf",
            "filename": "旧PDF.pdf",
            "page": 3,
            "doc_kind": "contract",
            "article_seq": None,
            "article_number": "第17条（原状回復義務等）",
        }
    )
    assert "第17条" in ref


def test_build_source_reference_important_matters_section():
    d = Document(
        page_content="表…",
        metadata={
            "type": "pdf",
            "filename": "重要事項説明書.txt",
            "doc_kind": "important_matters",
            "section_id": "12",
            "section_label": "12. 水防法の規定により",
        },
    )
    ref = build_source_reference([d])
    assert "重要事項説明書.txt" in ref
    assert "§12" in ref


def test_render_b2_includes_four_blocks_and_management():
    a = AnswerSchema(
        items=[AnswerItem(text="item1", citation="c1")],
        summary="要約本文です。",
        evidence=["e1"],
        next_action="（schema上の次アクション）",
        caveats="注意",
    )
    object.__setattr__(a, "display_format", DISPLAY_FORMAT_B2)
    object.__setattr__(a, "source_reference", "基本契約.pdf 第10条 p.5")

    out = render_answer_text(a)
    assert B2_HEADING_SOURCE in out
    assert B2_HEADING_SUMMARY in out
    assert B2_HEADING_CAVEAT in out
    assert B2_HEADING_NEXT in out
    assert "管理会社" in out
    assert "要約本文" in out
    assert "基本契約.pdf" in out


def test_format_b2_falls_back_summary_from_items():
    a = AnswerSchema(
        items=[AnswerItem(text="条項要約1", citation="x")],
        summary="",
        evidence=[],
        next_action="",
        caveats="",
    )
    object.__setattr__(a, "display_format", DISPLAY_FORMAT_B2)
    object.__setattr__(a, "source_reference", "契約.pdf p.1")
    out = format_b2_contract_rag_display(a)
    assert "条項要約" in out


def test_low_relevance_style_answer_not_four_block():
    """Simulate low-relevance fallback: no display_format on AnswerSchema."""
    a = AnswerSchema(
        items=[AnswerItem(text="該当する情報を確認できませんでした。管理会社へお問い合わせください。", citation="")],
        summary="該当する情報を確認できませんでした。管理会社へお問い合わせください。",
        evidence=[],
        next_action="管理会社へお問い合わせください",
        caveats="根拠と質問の整合が低いため、フォールバックしました。",
    )
    out = render_answer_text(a)
    assert B2_HEADING_SOURCE not in out
    assert "【注意点】" not in out
    assert "【該当箇所】" not in out
    assert "該当する情報" in out
