"""Important matters section split yields section_id and hazard table together."""

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from src.document_loader import load_txt_documents
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


class TestImportantMattersIndexing:
    """重要事項説明書.txt が MASTER_TXT_FILES に含まれ正しく取り込まれることを確認。"""

    def _make_config(self, master_txt_files: str) -> object:
        from src.config import Config

        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "sk-test",
                "MASTER_TXT_FILES": master_txt_files,
            },
        ):
            return Config()

    def test_load_txt_documents_includes_both_files(self) -> None:
        """MASTER_TXT_FILES に両ファイルを指定したとき、重要事項説明書チャンクが含まれる。"""
        cfg = self._make_config(
            "グランマーレ大分空港契約書.txt,重要事項説明書.txt"
        )
        docs = load_txt_documents(cfg)
        sources = {d.metadata.get("filename", "") for d in docs}
        assert "重要事項説明書.txt" in sources, "重要事項説明書.txt が未取り込み"
        assert "グランマーレ大分空港契約書.txt" in sources

    def test_load_txt_documents_contract_only_missing_important_matters(self) -> None:
        """契約書のみを指定すると重要事項説明書チャンクが取り込まれないことを確認（回帰防止）。"""
        cfg = self._make_config("グランマーレ大分空港契約書.txt")
        docs = load_txt_documents(cfg)
        sources = {d.metadata.get("filename", "") for d in docs}
        assert "重要事項説明書.txt" not in sources

    def test_important_matters_chunks_have_correct_doc_kind(self) -> None:
        """重要事項説明書チャンクのメタデータ doc_kind が important_matters であること。"""
        cfg = self._make_config(
            "グランマーレ大分空港契約書.txt,重要事項説明書.txt"
        )
        docs = load_txt_documents(cfg)
        im_docs = [d for d in docs if d.metadata.get("filename") == "重要事項説明書.txt"]
        assert im_docs, "重要事項説明書チャンクが0件"
        for d in im_docs:
            assert d.metadata.get("doc_kind") == "important_matters", (
                f"doc_kind が important_matters でない: {d.metadata}"
            )

    def test_important_matters_section3_indexed(self) -> None:
        """§3（賃料・管理費）チャンクが取り込まれていること。"""
        cfg = self._make_config(
            "グランマーレ大分空港契約書.txt,重要事項説明書.txt"
        )
        docs = load_txt_documents(cfg)
        im_docs = [d for d in docs if d.metadata.get("filename") == "重要事項説明書.txt"]
        joined = "\n".join(d.page_content for d in im_docs)
        assert "賃料" in joined or "管理費" in joined, "§3 の賃料・管理費内容が未取り込み"

    def test_important_matters_asbestos_section_indexed(self) -> None:
        """石綿（アスベスト）節チャンクが取り込まれていること。"""
        cfg = self._make_config(
            "グランマーレ大分空港契約書.txt,重要事項説明書.txt"
        )
        docs = load_txt_documents(cfg)
        im_docs = [d for d in docs if d.metadata.get("filename") == "重要事項説明書.txt"]
        joined = "\n".join(d.page_content for d in im_docs)
        assert "石綿" in joined or "アスベスト" in joined, "石綿節が未取り込み"


class TestContractSourceNotFoundMessage:
    """_contract_source_not_found_answer が正しい文言を返すことを確認。"""

    def test_not_found_message_includes_important_matters(self) -> None:
        """フォールバックメッセージに「重要事項説明書」が含まれること（契約書固定文言の回帰防止）。"""
        from unittest.mock import MagicMock
        from src.rag_answerer import RAGAnswerer

        answerer = MagicMock(spec=RAGAnswerer)
        answerer._contract_source_not_found_answer = RAGAnswerer._contract_source_not_found_answer.__get__(
            answerer, RAGAnswerer
        )
        result = answerer._contract_source_not_found_answer("§3の月額費用は？")
        msg = result.summary or (result.items[0].text if result.items else "")
        assert "重要事項説明書" in msg, f"フォールバックメッセージに重要事項説明書が含まれない: {msg!r}"
        assert "契約書" in msg


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
