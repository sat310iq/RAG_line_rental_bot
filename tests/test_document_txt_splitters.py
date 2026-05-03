"""Important matters section split yields section_id and hazard table together."""

from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from src.document_txt_splitters import (
    split_important_matters_txt_to_documents,
)
from src.retrieval_metadata_boost import apply_master_document_boost


def test_split_important_matters_section_12_contains_hazard_table() -> None:
    raw = Path(__file__).resolve().parent.parent / "data" / "documents" / "重要事項説明書.txt"
    text = raw.read_text(encoding="utf-8")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", "。", "．", "；", ";", "、", " ", ""],
    )
    docs = split_important_matters_txt_to_documents(
        sanitized_text=text,
        txt_path=raw,
        doc_kind="important_matters",
        text_splitter=splitter,
    )
    sec12 = [d for d in docs if (d.metadata or {}).get("section_id") == "12"]
    assert sec12
    joined = "\n".join(d.page_content for d in sec12)
    assert "洪水浸水想定区域" in joined
    assert "高潮浸水想定区域" in joined


def test_retrieval_boost_article_order() -> None:
    d17 = Document(
        page_content="第17条本文",
        metadata={
            "type": "master_txt",
            "filename": "契約.txt",
            "doc_kind": "contract",
            "article_number": "第17条（原状回復義務等）",
            "article_seq": 17,
        },
    )
    d4 = Document(
        page_content="第4条",
        metadata={
            "type": "master_txt",
            "filename": "契約.txt",
            "doc_kind": "contract",
            "article_number": "第4条（賃料）",
            "article_seq": 4,
        },
    )
    out, trace = apply_master_document_boost(
        "本文第17条の原則は",
        [d4, d17],
        contract_source_q=True,
    )
    assert "第17条" in (out[0].metadata.get("article_number") or "")
    assert trace
