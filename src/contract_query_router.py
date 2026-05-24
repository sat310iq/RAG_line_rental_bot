"""Detect questions that ask for wording in the lease contract (master), not general FAQ."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Sequence
from src.contract_query_intent import detect_article_reference, detect_usage_purpose_intent

# NFKC 後にマッチさせる（全角数字・括弧は正規表現側で吸収）

_RE_ARTICLE = re.compile(r"第\s*\d+\s*条")
_RE_TOKUYAKU = re.compile(r"特約\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫0-9０-９]+")
_RE_HEAD = re.compile(r"頭書")
_RE_HYOBU = re.compile(r"別表")
_RE_GENSHO_HYOBU = re.compile(r"原状回復の別表")
_RE_HONBUN = re.compile(r"契約書本文")
_RE_HONBUN_ARTICLE = re.compile(r"本文第\s*\d+\s*条")
_RE_REIKAI = re.compile(r"例外特約")
_RE_TAIKYO_CLEAN = re.compile(r"退去時クリーニング")
_RE_NENCHU = re.compile(r"経過年数")
_RE_KEIYAKU_JOKO = re.compile(r"契約条項")
_RE_USAGE_PURPOSE = re.compile(r"(使用目的|居住目的|居住のみを目的|用途)")
# 床材・内装への物理的損傷 + 費用負担 → 第17条（原状回復）への seed routing（MH-04 系）
_RE_FLOORING_DAMAGE = re.compile(
    r"(フローリング|床材|畳|フローリング材).*(へこ|傷|損傷|剥が|割れ|欠け)"
    r"|へこ.*(フローリング|床材|畳)"
)
_RE_IMPORTANT_MATTERS_DOC = re.compile(r"重要事項説明書")
# 「重」抜けタイポ（要事項説明書）をフォールバックとして許容
_RE_JUYO_SETSUMEISHO_TYPO = re.compile(r"要事項説明書")
_RE_JUSETSU = re.compile(r"重説")
_RE_JUYO_SECTION = re.compile(r"重要事項[^\n]{0,40}の\s*[0-9０-９一二三四五六七八九十]+[\.．]")
_RE_SECTION_NUM_JUYO = re.compile(r"重要事項[^\n]{0,48}の\s*([0-9０-９]+)")
# 「重説のN項目」「重説のN番」形式（重要事項 → 重説 略称）
_RE_SECTION_NUM_JUSETSU = re.compile(r"重説[^\n]{0,20}の\s*([0-9０-９]+)")
_RE_SECTION_NUM_BARE = re.compile(r"(?:^|[\s、,の])([0-9０-９]+)\s*(?:番|項目)")

IMPORTANT_MATTERS_HINTS: tuple[str, ...] = (
    "重要事項",
    "重要事項説明書",
    "ハザード",
    "洪水",
    "高潮",
    "浸水",
    "水防法",
    "土砂災害",
    "津波",
    "重説",
)

# Keyword-to-section mapping for deterministic inject into 重要事項説明書 (§1–§21).
# Used by extract_important_matters_section_id when no explicit section number is found.
# Order: longer/more-specific phrases first to avoid premature short-keyword match.
_IM_KEYWORD_SECTION_MAP: tuple[tuple[str, str], ...] = (
    # §1 登記簿に記録された事項
    ("所有権移転", "1"),
    ("登記簿", "1"),
    ("抵当権", "1"),
    # §2 契約期間及び更新に関する事項
    ("普通借家", "2"),
    ("定期借家", "2"),
    ("更新料", "2"),
    # §3 賃料及び賃料以外に授受される金額
    ("水道料", "3"),
    ("月額費用", "3"),
    ("初期費用", "3"),
    # §4 水道・電気・ガスの供給施設及び排水施設の整備状況
    ("排水施設", "4"),
    ("供給施設", "4"),
    # §5 建物の設備の整備状況
    ("設備の整備", "5"),
    # §6 建物建築の工事完了時における形状、構造等
    ("未完成物件", "6"),
    # §7 法令に基づく制限の概要
    ("建ぺい率", "7"),
    ("容積率", "7"),
    ("用途地域", "7"),
    ("法令制限", "7"),
    # §8 契約の解除に関する事項
    ("借主の解約予告", "8"),
    ("貸主による解除", "8"),
    ("無催告解除", "8"),
    # §9 損害賠償額の予定または違約金に関する事項
    ("損害賠償額の予定", "9"),
    # §10 支払金または預り金の保全措置の概要
    ("保全措置", "10"),
    ("預り金", "10"),
    # §11 当該建物の存ずる区域
    ("土砂災害", "11"),
    ("津波", "11"),
    # §12 水防法の規定による水害ハザードマップ
    ("高潮", "12"),
    ("浸水", "12"),
    ("水防法", "12"),
    ("ハザード", "12"),
    ("洪水", "12"),
    # §13 石綿使用調査内容
    ("アスベスト", "13"),
    ("石綿", "13"),
    # §14 耐震診断の内容
    ("耐震診断", "14"),
    ("耐震", "14"),
    # §15 建物状況調査の内容
    ("インスペクション", "15"),
    ("建物状況調査", "15"),
    # §16 用途その他の利用の制限に関する事項
    ("用途制限", "16"),
    # §17 敷金の精算に関する事項
    ("敷金の精算", "17"),
    # §18 金銭の貸借のあっせん
    ("金銭の貸借", "18"),
    # §19 建物管理の委託先
    ("管理の委託", "19"),
    ("委託先", "19"),
    # §21 供託所等に関する説明
    ("供託所", "21"),
    ("供託", "21"),
)

# Keyword-to-article mapping for 賃貸借契約書（第1条–第26条）.
# Used by extract_contract_article_index when no explicit 第X条 reference is found.
# Order: longer/more-specific phrases first.
_CONTRACT_KEYWORD_ARTICLE_MAP: tuple[tuple[str, int], ...] = (
    # 第3条 使用目的は detect_usage_purpose_intent で既に処理 → ここでは定義しない
    # 第4条 賃料
    ("賃料の支払方法", 4),
    ("家賃の支払", 4),
    # 第5条 管理費・共益費等
    ("共益費", 5),
    ("管理費", 5),
    # 第6条 諸経費の負担
    ("諸経費", 6),
    # 第7条 敷金
    ("敷金の返還", 7),
    ("敷金", 7),
    # 第8条 反社会的勢力の排除
    ("反社会的勢力", 8),
    ("暴力団", 8),
    # 第9条 善管注意義務
    ("善管注意義務", 9),
    # 第10条 禁止又は制限される行為
    ("禁止行為", 10),
    ("禁止事項", 10),
    # 第11条 契約期間中の修繕
    ("修繕", 11),
    # 第12条 一部滅失等による賃料の減額等
    ("一部滅失", 12),
    ("賃料の減額", 12),
    # 第13条 契約の解除
    ("催告による解除", 13),
    # 第14条 解約の申し入れ
    ("退去通知", 14),
    ("解約予告", 14),
    # 第16条 明渡し
    ("明渡し", 16),
    # 第17条 原状回復義務等
    ("原状回復", 17),
    ("フローリング", 17),  # 床材損傷 → 原状回復 (MH-04)
    ("床材", 17),
    # 第18条 更新
    ("更新手続", 18),
    # 第19条 有益費の償還等
    ("有益費", 19),
    # 第20条 立入り
    ("立入検査", 20),
    ("立入り", 20),
    # 第21条 連帯保証人
    ("連帯保証人", 21),
    # 第22条 家賃債務保証業者の提供する保証
    ("家賃債務保証", 22),
    # 第24条 遅延損害金
    ("遅延損害金", 24),
    # 第25条 合意管轄裁判所
    ("管轄裁判所", 25),
    ("合意管轄", 25),
)


def _normalize_question(question: str) -> str:
    return unicodedata.normalize("NFKC", question or "")


def is_contract_source_question(
    question: str,
    extra_regex: Optional[Sequence[str]] = None,
) -> bool:
    """True if the user is asking what the contract document says (article, 特約, 別表, etc.).

    「契約書」単独や「契約更新」等の一般相談では True にしない。
    """
    q = _normalize_question(question)
    if not q.strip():
        return False

    if _RE_ARTICLE.search(q):
        return True
    if _RE_TOKUYAKU.search(q):
        return True
    if _RE_HEAD.search(q):
        return True
    if _RE_GENSHO_HYOBU.search(q):
        return True
    if _RE_HYOBU.search(q):
        return True
    if _RE_HONBUN.search(q):
        return True
    if _RE_HONBUN_ARTICLE.search(q):
        return True
    if _RE_REIKAI.search(q):
        return True

    # 契約書 + 記載系（「契約書」単独は不可）
    if "契約書" in q and any(
        x in q for x in ("記載", "書いて", "書かれ", "定め", "規定")
    ):
        return True

    # 契約条項 + 内容・関係を問う（契約書本文の条項そのものを尋ねる）
    if _RE_KEIYAKU_JOKO.search(q) and any(
        x in q for x in ("記載", "書いて", "書かれ", "定め", "規定", "内容", "関係", "について")
    ):
        return True

    _meta = ("記載", "書いて", "書かれ", "どのように", "例として", "について")
    if _RE_TAIKYO_CLEAN.search(q) and any(m in q for m in _meta):
        return True
    if "設備の経過年数" in q or (
        _RE_NENCHU.search(q) and any(m in q for m in ("負担割合", "記載", "書いて", "書かれ", "について"))
    ):
        return True

    if _RE_IMPORTANT_MATTERS_DOC.search(q):
        return True
    if _RE_JUSETSU.search(q):
        return True
    if "重要事項" in q and "説明書" in q:
        return True
    # 「重」抜けタイポ（要事項説明書）でもマスター参照として扱う
    if _RE_JUYO_SETSUMEISHO_TYPO.search(q):
        return True
    if "重要事項" in q and any(
        m in q
        for m in (
            "記載",
            "書いて",
            "書かれ",
            "定め",
            "規定",
            "どのように",
            "どう書",
            "何が",
            "いくら",
            "教えて",
        )
    ):
        return True
    if _RE_JUYO_SECTION.search(q):
        return True

    # 賃貸借の目的物・建物表示（マスター契約の定型記載を問うもの）
    if "目的物" in q and any(
        m in q
        for m in (
            "記載",
            "書いて",
            "書かれ",
            "契約書",
            "頭書",
            "別表",
            "条",
            "特約",
            "どこ",
            "定め",
            "規定",
        )
    ):
        return True

    # 条番号なしでも「契約の使用目的/用途」を聞く質問は契約本文参照として扱う
    if _RE_USAGE_PURPOSE.search(q) and detect_usage_purpose_intent(q):
        return True

    if "短期解約違約金" in q:
        return True
    if "違約金" in q and any(m in q for m in ("いくら", "幾ら", "金額", "何ヶ月", "何カ月")):
        return True

    # 床材・内装の物理的損傷 → 原状回復（第17条）への seed routing（MH-04 系）
    if _RE_FLOORING_DAMAGE.search(q):
        return True

    # 水道料超過 → 特約①（水道料の超過分）への seed routing（XD-01 系）
    if any(x in q for x in ("水道代", "水道料")) and any(x in q for x in ("超え", "超過")):
        return True

    if extra_regex:
        for pat in extra_regex:
            if pat and re.search(pat, q):
                return True

    return False


def is_important_matters_question(question: str) -> bool:
    """True if query is likely about 重要事項説明書 content (hazard, flood, etc.)."""
    q = _normalize_question(question)
    if not q.strip():
        return False
    return any(h in q for h in IMPORTANT_MATTERS_HINTS)


def extract_contract_article_index(question: str) -> Optional[int]:
    """Parse 本文第17条 / 第4条 style references; falls back to _CONTRACT_KEYWORD_ARTICLE_MAP."""
    result = detect_article_reference(question)
    if result is not None:
        return result
    q = _normalize_question(question)
    for kw, article_idx in _CONTRACT_KEYWORD_ARTICLE_MAP:
        if kw in q:
            return article_idx
    return None


def extract_important_matters_section_id(question: str) -> Optional[str]:
    """Parse section number for 重要事項の12 / 重説の3項目 / 12番 style queries (NFKC digits only).

    Falls back to keyword-to-section mapping (_IM_KEYWORD_SECTION_MAP) for queries
    that omit an explicit section number (e.g. 洪水リスク → §12, 水道料 → §3).
    """
    q = _normalize_question(question)
    m = _RE_SECTION_NUM_JUYO.search(q)
    if m:
        raw = m.group(1)
        return "".join(c for c in unicodedata.normalize("NFKC", raw) if c.isdigit()) or None
    m = _RE_SECTION_NUM_JUSETSU.search(q)
    if m:
        raw = m.group(1)
        return "".join(c for c in unicodedata.normalize("NFKC", raw) if c.isdigit()) or None
    if "重要" in q or "重説" in q:
        m2 = _RE_SECTION_NUM_BARE.search(q)
        if m2:
            raw = m2.group(1)
            return "".join(c for c in unicodedata.normalize("NFKC", raw) if c.isdigit()) or None
    for kw, sid in _IM_KEYWORD_SECTION_MAP:
        if kw in q:
            return sid
    return None


def prefers_contract_master_chunks(question: str) -> bool:
    """When splitting boost between contract TXT vs 重要事項, prefer contract chunks."""
    q = _normalize_question(question)
    if extract_contract_article_index(question) is not None:
        return True
    if _RE_HONBUN_ARTICLE.search(q) or _RE_HEAD.search(q) or _RE_TOKUYAKU.search(q):
        return True
    if "本文" in q and "条" in q:
        return True
    return False
