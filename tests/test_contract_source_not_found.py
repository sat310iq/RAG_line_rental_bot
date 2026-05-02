"""Contract-source path returns not_found schema without FAQ evidence."""

from src.rag_answerer import RAGAnswerer


def test_contract_source_not_found_answer_shape() -> None:
    rag = RAGAnswerer.__new__(RAGAnswerer)
    ans = rag._contract_source_not_found_answer("本文第17条の原則は？")
    assert ans.evidence == []
    assert ans.summary == "契約書（根拠情報）内では確認できません。"
    assert ans.items and "確認できません" in ans.items[0].text
