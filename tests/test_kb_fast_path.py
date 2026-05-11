"""Tests for KB fast path scoring and clarification."""

from __future__ import annotations

import os

import pytest

from src.config import load_config, reset_config
from src.kb_fast_path import normalize_for_match, try_kb_fast_path
from src.kb_loader import load_kb_csv


@pytest.fixture
def cfg():
    reset_config()
    os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "sk-test-dummy"))
    c = load_config(force_reload=True)
    return c


def test_gas_fee_specific_hits(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス料金を知りたいのですが", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "生活_ガス料金"
    assert "ダイプロ" in (r.text or "")


def test_gas_fault_hits(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス給湯器が故障したようです", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "設備_ガス故障"


def test_gas_water_heater_no_hot_water_is_hit_not_short_clarification_loop(cfg):
    """Production bug: len(norm)==12 with short_max_len=12 treated query as 'short' → clarification loop."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス給湯器のお湯が出ない", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "設備_ガス故障"
    assert r.text and "ダイプロ" in r.text


def test_smoking_parity(cfg):
    docs = load_kb_csv(cfg)
    r1 = try_kb_fast_path("喫煙は可能ですか", cfg, docs)
    r2 = try_kb_fast_path("タバコを吸っても良いですか", cfg, docs)
    assert r1.kind == "hit"
    assert r2.kind == "hit"
    assert r1.intent == "生活_喫煙"
    assert r2.intent == "生活_喫煙"


def test_gas_short_clarification(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("ガス", cfg, docs)
    assert r.kind == "clarification"
    assert r.text and "どれ" in r.text
    assert "1." in r.text and "そのまま次のように送ってください。" in r.text
    assert "上の 1〜3 の番号だけでも返信できます。" in (r.text or "")
    assert r.match_detail.get("clarification_reason") == "short_query"
    nq = r.match_detail.get("clarification_numeric_queries")
    assert isinstance(nq, list) and len(nq) == 3


def test_certificate_short_clarification(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("証明書", cfg, docs)
    assert r.kind == "clarification"
    assert "1." in (r.text or "") and "- " in (r.text or "")


def test_hot_water_short_phrase_is_hit(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("お湯が出ない", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "設備_ガス故障"
    assert r.match_detail.get("is_specific_even_if_short") is True


def test_certificate_full_sentence_is_hit(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("証明書を発行したい", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "契約_証明書"
    assert "To You" in (r.text or "") or "0978" in (r.text or "")


def test_prior_clarification_same_vague_short_repeat_stays_clarification(cfg):
    """Same intent + same normalized short text: do not relax short → stay clarification."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path(
        "ガス",
        cfg,
        docs,
        prior_clarification_intent="生活_ガス料金",
        prior_clarification_normalized_query=normalize_for_match("ガス"),
    )
    assert r.kind == "clarification"
    assert r.intent == "生活_ガス料金"
    assert r.match_detail.get("clarification_reason") == "short_query"


def test_prior_clarification_legacy_none_normalized_still_relaxes_short(cfg):
    """Migration: prior normalized_query omitted → legacy hit on repeat ガス (remove when unused)."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path(
        "ガス",
        cfg,
        docs,
        prior_clarification_intent="生活_ガス料金",
        prior_clarification_normalized_query=None,
    )
    assert r.kind == "hit"
    assert r.intent == "生活_ガス料金"


def test_prior_clarification_same_intent_different_norm_hits(cfg):
    """Concrete follow-up after ガス clarification: different normalized text → hit."""
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path(
        "ガス料金を知りたいのですが",
        cfg,
        docs,
        prior_clarification_intent="生活_ガス料金",
        prior_clarification_normalized_query=normalize_for_match("ガス"),
    )
    assert r.kind == "hit"
    assert r.intent == "生活_ガス料金"


def test_legal_skip_misses(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("これは違法ではないですか", cfg, docs)
    assert r.kind == "miss"


def test_vague_repair_question_clarifies(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("修繕について教えてください", cfg, docs)
    assert r.kind == "clarification"
    assert r.intent == "設備_故障"
    assert r.match_detail.get("clarification_reason") == "ambiguous_topic"


def test_vague_water_question_clarifies(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("水道の件なんですが", cfg, docs)
    assert r.kind == "clarification"
    assert r.intent == "生活_水道請求"
    assert r.match_detail.get("clarification_reason") == "ambiguous_topic"


def test_vague_contract_question_clarifies(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("契約について聞きたい", cfg, docs)
    assert r.kind == "clarification"
    assert r.intent == "契約_更新"
    assert r.match_detail.get("clarification_reason") == "ambiguous_topic"


def test_vague_renewal_question_clarifies(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("更新の件です", cfg, docs)
    assert r.kind == "clarification"
    assert r.intent == "契約_更新"
    assert r.match_detail.get("clarification_reason") == "ambiguous_topic"


def test_water_billing_specific_still_hits(cfg):
    docs = load_kb_csv(cfg)
    r = try_kb_fast_path("水道料金の明細を確認したい", cfg, docs)
    assert r.kind == "hit"
    assert r.intent == "生活_水道請求"


_GARBAGE_INTENTS = ("ゴミ出し_ルール", "ゴミステーション_共用部")
# 市のゴミ収集ルール本文（清掃費の質問に返すと誤解を招く）
_GARBAGE_CITY_RULE_MARKERS = ("国東市のゴミ出しルール", "gomikeikakuhyou", "ゴミ収集計画表")


def test_cleaning_fee_questions_do_not_map_to_garbage_intent(cfg):
    docs = load_kb_csv(cfg)
    for q in (
        "清掃費って払うの？",
        "退去清掃費は必要ですか？",
        "クリーニング代は誰が払いますか？",
    ):
        r = try_kb_fast_path(q, cfg, docs)
        assert r.intent not in _GARBAGE_INTENTS, (q, r.intent, r.kind)


def test_cleaning_fee_hits_not_city_garbage_rule_answer(cfg):
    docs = load_kb_csv(cfg)
    for q in (
        "清掃費って払うの？",
        "退去清掃費は必要ですか？",
        "クリーニング代は誰が払いますか？",
    ):
        r = try_kb_fast_path(q, cfg, docs)
        if r.kind == "hit" and r.text:
            for m in _GARBAGE_CITY_RULE_MARKERS:
                assert m not in r.text, (q, m)


def test_fast_path_disabled(cfg):
    docs = load_kb_csv(cfg)
    cfg.kb_fast_path_enabled = False
    r = try_kb_fast_path("ガス料金を知りたい", cfg, docs)
    assert r.kind == "miss"


def test_kb_fast_path_short_term_penalty_hit(cfg):
    """REQ: 短期解約違約金 - fast path で hit し answer に金額が含まれること"""
    docs = load_kb_csv(cfg)
    for question in [
        "短期解約の違約金はいくらですか？",
        "違約金いくら？",
    ]:
        r = try_kb_fast_path(question, cfg, docs)
        assert r.kind == "hit", f"expected hit, got {r.kind} for '{question}'"
        assert r.intent == "契約_短期解約違約金", (
            f"intent mismatch for '{question}': {r.intent}"
        )
        assert any(
            amount in (r.text or "")
            for amount in ["114,600", "76,400", "38,200"]
        ), f"金額が answer に含まれない: {r.text}"


# ---------------------------------------------------------------------------
# TASK-008: 9 newly enabled intents — fast path coverage regression tests
# ---------------------------------------------------------------------------


class TestTask008NewIntents:
    """Verify that the 9 intents enabled in TASK-008 return fast-path hits."""

    def _hit(self, cfg, docs, query: str, expected_intent: str) -> None:
        r = try_kb_fast_path(query, cfg, docs)
        assert r.kind == "hit", f"expected hit for {query!r}, got kind={r.kind}"
        assert r.intent == expected_intent, (
            f"intent mismatch for {query!r}: got={r.intent!r}, want={expected_intent!r}"
        )
        assert r.text, f"answer text is empty for {query!r}"

    def test_suspicious_person_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "不審者を見かけました", "防犯_不審者")
        self._hit(cfg, docs, "怪しい人物が歩き回っています", "防犯_不審者")

    def test_pet_policy_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "犬を飼ってもいいですか", "ペット飼育の可否")
        self._hit(cfg, docs, "ペット可ですか？", "ペット飼育の可否")
        self._hit(cfg, docs, "猫を飼育したいのですが", "ペット飼育の可否")

    def test_fire_alarm_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "火災警報器が鳴っています", "設備_火災警報")
        self._hit(cfg, docs, "煙感知器が反応しています", "設備_火災警報")

    def test_common_area_lighting_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "廊下の電気が切れています", "設備_共用部照明")
        self._hit(cfg, docs, "共用部の照明が消えています", "設備_共用部照明")
        self._hit(cfg, docs, "玄関の照明がチカチカしています", "設備_共用部照明")

    def test_common_area_lighting_no_false_hit_on_denki(self, cfg):
        """'電気' alone should NOT hit 設備_共用部照明 (would beat 生活_電気)."""
        docs = load_kb_csv(cfg)
        r = try_kb_fast_path("電気", cfg, docs)
        assert r.intent != "設備_共用部照明", (
            f"False hit: '電気' should not resolve to 設備_共用部照明, got {r.intent!r}"
        )

    def test_garbage_rule_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "ゴミ出しの曜日を教えてください", "ゴミ出し_ルール")
        self._hit(cfg, docs, "燃えるゴミはいつ出せますか", "ゴミ出し_ルール")
        self._hit(cfg, docs, "ゴミの分別方法を教えてください", "ゴミ出し_ルール")

    def test_garbage_station_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "ゴミステーションが散らかっています", "ゴミステーション_共用部")
        self._hit(cfg, docs, "ゴミ置き場が汚いです", "ゴミステーション_共用部")

    def test_restoration_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "退去時の原状回復の費用は誰が負担しますか", "契約_原状回復")
        self._hit(cfg, docs, "経年劣化は借主負担ですか", "契約_原状回復")
        self._hit(cfg, docs, "通常損耗は借主負担になりますか", "契約_原状回復")

    def test_parking_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "駐車場の利用方法を教えてください", "駐車場_利用")
        self._hit(cfg, docs, "駐車場の番号はどこで確認できますか", "駐車場_利用")

    def test_management_contact_hit(self, cfg):
        docs = load_kb_csv(cfg)
        self._hit(cfg, docs, "管理会社の電話番号を教えてください", "管理会社_連絡先")
        self._hit(cfg, docs, "To Youの連絡先を教えてください", "管理会社_連絡先")
        self._hit(cfg, docs, "0978の電話番号はどこですか", "管理会社_連絡先")
