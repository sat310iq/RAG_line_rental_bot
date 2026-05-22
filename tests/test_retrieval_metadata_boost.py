from langchain_core.documents import Document

from src.retrieval_metadata_boost import (
    apply_master_document_boost,
    _is_tokuyaku_penalty_question,
    _is_tokuyaku_penalty_chunk,
)


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


# ---------------------------------------------------------------------------
# PR-1c: 特約④ / 短期解約違約金 boost
# ---------------------------------------------------------------------------

def _tokuyaku_doc(*, content: str, article_number: str = "特約") -> Document:
    return Document(
        page_content=content,
        metadata={
            "type": "master_txt",
            "doc_kind": "contract",
            "article_number": article_number,
            "filename": "契約書.txt",
        },
    )


# --- _is_tokuyaku_penalty_question 単体 ---

def test_tokuyaku_penalty_question_fires_on_iyakukin_ikura() -> None:
    assert _is_tokuyaku_penalty_question("違約金はいくらですか？") is True


def test_tokuyaku_penalty_question_fires_on_tankikaiyaku() -> None:
    assert _is_tokuyaku_penalty_question("短期解約した場合の費用は？") is True


def test_tokuyaku_penalty_question_not_fired_for_general_iyakukin() -> None:
    # 「違約金について教えて」は金額キーワードなし → False（KB 経路回帰）
    assert _is_tokuyaku_penalty_question("違約金について教えて") is False


def test_tokuyaku_penalty_question_not_fired_when_numbered_tokuyaku() -> None:
    # T3: 番号付き特約が明示 → False（既存ロジック優先）
    assert _is_tokuyaku_penalty_question("特約④の内容を教えてください") is False
    assert _is_tokuyaku_penalty_question("特約⑤はどうなっていますか") is False


# --- _is_tokuyaku_penalty_chunk 単体 ---

def test_tokuyaku_penalty_chunk_matches_content_with_tankikaiyaku_iyakukin() -> None:
    doc = _tokuyaku_doc(content="特約④（短期解約違約金）6ヶ月以内 114,600円")
    assert _is_tokuyaku_penalty_chunk(doc) is True


def test_tokuyaku_penalty_chunk_not_matches_unrelated_article() -> None:
    doc = _doc(24, content="第24条 遅延損害金 年14.6%")
    assert _is_tokuyaku_penalty_chunk(doc) is False


# --- apply_master_document_boost 統合 ---

def test_tokuyaku_penalty_boost_fires_and_moves_to_front() -> None:
    """違約金+金額クエリで特約④ chunk が先頭になること（PR-1c）。"""
    penalty_chunk = _tokuyaku_doc(
        content="特約④（短期解約違約金）6ヶ月以内 114,600円",
        article_number="特約④",
    )
    docs = [
        _doc(24, content="第24条 遅延損害金 年14.6%"),
        penalty_chunk,
    ]
    boosted, trace = apply_master_document_boost(
        "違約金はいくら？",
        docs,
        contract_source_q=True,
    )
    assert boosted[0] is penalty_chunk
    reasons = [t.get("boost_reason", "") for t in trace]
    assert any("tokuyaku_penalty_clause" in r for r in reasons)


def test_tokuyaku_penalty_boost_not_fired_for_general_query() -> None:
    """「特約について教えて」では boost が発火しないこと（T2 不成立）。"""
    docs = [
        _doc(24, content="第24条 遅延損害金"),
        _tokuyaku_doc(content="特約④（短期解約違約金）114,600円"),
    ]
    _, trace = apply_master_document_boost(
        "特約について教えて",
        docs,
        contract_source_q=True,
    )
    reasons = [t.get("boost_reason", "") for t in trace]
    assert not any("tokuyaku_penalty" in r for r in reasons)


def test_tokuyaku_penalty_boost_not_fired_for_numbered_tokuyaku_query() -> None:
    """番号付き特約クエリは T3 でブロック、二重 boost なし。"""
    docs = [
        _doc(24, content="第24条 遅延損害金"),
        _tokuyaku_doc(content="特約④（短期解約違約金）114,600円"),
    ]
    _, trace = apply_master_document_boost(
        "特約④の内容を教えてください",
        docs,
        contract_source_q=True,
    )
    reasons = [t.get("boost_reason", "") for t in trace]
    assert not any("tokuyaku_penalty" in r for r in reasons)


def test_tokuyaku_penalty_boost_promotes_at_most_two_chunks() -> None:
    """最大2件しか promote しないこと（G6相当）。"""
    penalty_chunks = [
        _tokuyaku_doc(content=f"特約④ 短期解約違約金 variant{i}")
        for i in range(4)
    ]
    docs = [_doc(24)] + penalty_chunks
    boosted, trace = apply_master_document_boost(
        "短期解約の違約金はいくらですか",
        docs,
        contract_source_q=True,
    )
    promoted = [t for t in trace if t.get("boost_reason") == "tokuyaku_penalty_clause"]
    assert len(promoted) <= 2


# ---------------------------------------------------------------------------
# 1-D: is_important_matters boost runs even when contract_source_q=False
# ---------------------------------------------------------------------------

def test_important_matters_rest_sort_fires_without_contract_source_q() -> None:
    """ハザード系クエリは contract_source_q=False でも important_matters を先頭にソート。"""
    docs = [
        _doc(24),
        _im_doc("5", content="ハザードマップ 洪水リスク低"),
        _im_doc("7", content="津波リスク低"),
    ]
    boosted, _ = apply_master_document_boost(
        "洪水の危険性はありますか？",
        docs,
        contract_source_q=False,
    )
    assert boosted[0].metadata.get("doc_kind") == "important_matters"


def test_section_id_boost_fires_without_contract_source_q() -> None:
    """重説のN項目クエリで section_id boost が contract_source_q=False でも発火。"""
    docs = [
        _doc(24),
        _im_doc("5"),
        _im_doc("3", content="月額費用表 家賃31,700円"),
    ]
    boosted, trace = apply_master_document_boost(
        "重説の３項目では家賃はいくらですか",
        docs,
        contract_source_q=False,
    )
    assert boosted[0].metadata.get("section_id") == "3"
    reasons = [t.get("boost_reason", "") for t in trace]
    assert any("section_exact:3" in r for r in reasons)


def test_article_boost_not_fired_without_contract_source_q() -> None:
    """contract_source_q=False では article boost は発火しない。"""
    docs = [
        _doc(4),
        _doc(7),
        _doc(3, article_number="第3条（使用目的）", content="居住のみを目的"),
    ]
    _, trace = apply_master_document_boost(
        "重説の洪水リスクはどうなっていますか",
        docs,
        contract_source_q=False,
    )
    reasons = [t.get("boost_reason", "") for t in trace]
    assert not any("article_seq_exact" in r or "article_exact" in r for r in reasons)


def test_tokuyaku_penalty_boost_not_fired_without_contract_source_q() -> None:
    """contract_source_q=False では tokuyaku_penalty boost は発火しない。"""
    penalty_chunk = _tokuyaku_doc(
        content="特約④（短期解約違約金）6ヶ月以内 114,600円",
        article_number="特約④",
    )
    docs = [_doc(24), _im_doc("3"), penalty_chunk]
    _, trace = apply_master_document_boost(
        "洪水リスクと短期解約違約金はいくらですか",
        docs,
        contract_source_q=False,
    )
    reasons = [t.get("boost_reason", "") for t in trace]
    assert not any("tokuyaku_penalty" in r for r in reasons)


def test_no_boost_when_neither_contract_source_nor_imp_matters() -> None:
    """どちらのフラグも立たない一般クエリでは docs 順序が変わらない。"""
    docs = [_doc(4), _doc(7), _doc(3)]
    boosted, trace = apply_master_document_boost(
        "敷金はいくらですか",
        docs,
        contract_source_q=False,
    )
    assert boosted == docs
    assert trace == []
