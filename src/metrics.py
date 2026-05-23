"""Evaluation metrics v2 for RAG system (Decision Hygiene compliant).

This module provides evaluation metrics following Decision Hygiene principles:
- Diagnostic: Metrics indicate where to fix issues
- Layered: Separates Retrieval / Evaluation / Generation / Safety
- Conditional: Metrics are conditional on question type
- Actionable: Thresholds have clear meaning for decision making

Metrics v2 Structure:
- Retrieval Metrics: Recall@K (typed), Hit@1
- Evaluation Metrics: ID Normalization Success Rate, Multi-source Coverage
- Generation Metrics: Answer Completeness, Evidence Binding Rate, Over-summarization Rate
- Safety Metrics: Hallucination (decomposed), Prohibited Mention Rate (typed)
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal, Set, TYPE_CHECKING
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from src.question_typing import QuestionType

if TYPE_CHECKING:
    from src.rag_answerer import AnswerSchema


# ============================================================================
# Retrieval Metrics (検索品質)
# ============================================================================

def recall_topk_covers_expected(retrieved_ids: List[str], expected_ids: List[str], k: int) -> bool:
    """True if every expected ID appears in retrieved_ids[:k] (set coverage)."""
    if not expected_ids:
        return True
    top = set(retrieved_ids[:k])
    return set(expected_ids) <= top


def classify_match_tier(
    retrieved_ids: List[str],
    expected_ids_strict: List[str],
    expected_ids_normalized: List[str],
    k: int = 5,
) -> str:
    """3-way tier (week 1): strict_hit | normalized_only | miss.

    - strict_hit: every strict expected ID is in top-k.
    - normalized_only: not strict_hit, but every normalized expected ID is in top-k.
    - miss: otherwise.
    """
    if not expected_ids_strict and not expected_ids_normalized:
        return "unknown"
    strict_ok = recall_topk_covers_expected(retrieved_ids, expected_ids_strict, k)
    if strict_ok:
        return "strict_hit"
    norm_ok = recall_topk_covers_expected(retrieved_ids, expected_ids_normalized, k)
    if norm_ok:
        return "normalized_only"
    return "miss"


# OPIK feedback_scores: numeric only (strings go to metadata). See docs/eval/OPIK_DASHBOARD_RUNBOOK.md
MATCH_TIER_TO_CODE = {
    "strict_hit": 0,
    "normalized_only": 1,
    "miss": 2,
    "unknown": 3,
}


def match_tier_to_code(match_tier: Optional[str]) -> int:
    """Map match_tier string to integer for OPIK/Comet numeric-only fields."""
    if not match_tier:
        return MATCH_TIER_TO_CODE["unknown"]
    return MATCH_TIER_TO_CODE.get(match_tier, MATCH_TIER_TO_CODE["unknown"])


def compute_rag_aggregate_health(metrics: Dict[str, Any]) -> None:
    """Set rag_health_score, rag_health_pass, rag_health_summary on aggregate metrics dict (in-place).

    Weights: w1=0.5 recall@5 normalized, w2=0.3 (1-fact_error), w3=0.2 (1-miss_rate).
    Gates: normalized_recall > 0.4, fact_error_rate == 0, match_tier_miss_rate < 0.5 (when present).
    """
    w1, w2, w3 = 0.5, 0.3, 0.2
    nr = float(metrics.get("avg_recall_at_5", 0.0) or 0.0)
    fer = float(metrics.get("fact_error_rate", metrics.get("avg_hallucination_fact_error", 0.0)) or 0.0)
    miss_r = metrics.get("match_tier_miss_rate")
    miss_r_f = float(miss_r) if miss_r is not None else None

    if miss_r_f is not None:
        score = w1 * nr + w2 * (1.0 - fer) + w3 * (1.0 - miss_r_f)
    else:
        score = w1 * nr + w2 * (1.0 - fer) + w3 * 1.0
    metrics["rag_health_score"] = max(0.0, min(1.0, score))

    gate_recall = nr > 0.4
    gate_fact = fer == 0.0
    gate_miss = (miss_r_f < 0.5) if miss_r_f is not None else True
    passed = gate_recall and gate_fact and gate_miss
    metrics["rag_health_pass"] = 1.0 if passed else 0.0
    reasons = []
    if not gate_recall:
        reasons.append("avg_recall_at_5<=0.4")
    if not gate_fact:
        reasons.append("fact_error>0")
    if miss_r_f is not None and not gate_miss:
        reasons.append(f"miss_rate>={0.5}")
    metrics["rag_health_summary"] = "OK" if passed else "NG: " + "; ".join(reasons) if reasons else "NG"


def load_semantic_neighbor_pairs(path: Path) -> List[Dict[str, Any]]:
    """Load optional semantic neighbor classes YAML (week 2+). Empty pairs => []."""
    try:
        import yaml
    except ImportError:
        return []
    if not path.is_file():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    pairs = data.get("pairs") or []
    return pairs if isinstance(pairs, list) else []


def build_semantic_equivalence_map(pairs: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Map each doc id to the set of ids in its semantic class (including self)."""
    clusters: List[Set[str]] = []
    for p in pairs:
        if not isinstance(p, dict):
            continue
        anchor = p.get("anchor") or p.get("id")
        neigh = p.get("neighbors") or []
        if not isinstance(neigh, list):
            neigh = []
        members: Set[str] = set()
        if anchor:
            members.add(str(anchor))
        members.update(str(n) for n in neigh)
        if not members:
            continue
        merged: Set[str] = set(members)
        new_clusters: List[Set[str]] = []
        for c in clusters:
            if c & merged:
                merged |= c
            else:
                new_clusters.append(c)
        new_clusters.append(merged)
        clusters = new_clusters
    out: Dict[str, Set[str]] = {}
    for c in clusters:
        for x in c:
            out[x] = set(c)
    return out


def semantic_neighbor_hit(
    retrieved_ids: List[str],
    expected_ids_normalized: List[str],
    equivalence: Dict[str, Set[str]],
) -> bool:
    """True if top-1 retrieved is in the same semantic class as any expected normalized id."""
    if not retrieved_ids or not equivalence or not expected_ids_normalized:
        return False
    top1 = retrieved_ids[0]
    for exp in expected_ids_normalized:
        cluster = equivalence.get(exp)
        if cluster and top1 in cluster:
            return True
    return False


def calculate_retrieval_metrics_v2(
    retrieved_ids: List[str],
    expected_ids: List[str],
    question_type: Optional[QuestionType] = None,
    k_values: List[int] = [5, 10]
) -> Dict[str, Any]:
    """Calculate retrieval metrics v2 (typed Recall@K, Hit@1).
    
    Args:
        retrieved_ids: List of retrieved document IDs
        expected_ids: List of expected document IDs
        question_type: Question type (for typed metrics)
        k_values: List of K values for Recall@K calculation
        
    Returns:
        Dictionary with typed metrics:
        - recall_at_{k}: Overall recall
        - recall_at_{k}.{question_type}: Typed recall (if question_type provided)
        - hit_at_1: Hit@1 (for single-source questions only)
        - mrr: Mean Reciprocal Rank
    """
    if not expected_ids:
        metrics = {f"recall_at_{k}": 0.0 for k in k_values}
        metrics["mrr"] = 0.0
        metrics["hit_at_1"] = 0.0
        if question_type:
            for k in k_values:
                metrics[f"recall_at_{k}.{question_type}"] = 0.0
        return metrics
    
    metrics = {}
    
    # Calculate Recall@K for each k
    for k in k_values:
        retrieved_top_k = retrieved_ids[:k]
        relevant_retrieved = len(set(retrieved_top_k) & set(expected_ids))
        recall = relevant_retrieved / len(expected_ids) if expected_ids else 0.0
        metrics[f"recall_at_{k}"] = recall
        
        # Typed recall (if question_type provided)
        if question_type:
            metrics[f"recall_at_{k}.{question_type}"] = recall
    
    # Calculate MRR (Mean Reciprocal Rank)
    mrr = 0.0
    for rank, doc_id in enumerate(retrieved_ids, 1):
        if doc_id in expected_ids:
            mrr = 1.0 / rank
            break
    metrics["mrr"] = mrr
    
    # Calculate Hit@1 (for single-source questions only)
    # Only applicable for fact_lookup questions with single expected document
    hit_at_1 = 0.0
    if question_type == "fact_lookup" and len(expected_ids) == 1:
        if retrieved_ids and retrieved_ids[0] == expected_ids[0]:
            hit_at_1 = 1.0
    metrics["hit_at_1"] = hit_at_1
    
    # Warn if question_type is not provided
    if not question_type:
        import sys
        print("Warning: question_type not provided for retrieval metrics", file=sys.stderr)
    
    return metrics


# ============================================================================
# Evaluation Metrics (評価設計の健全性)
# ============================================================================

def calculate_id_normalization_success_rate(
    expected_ids: List[str],
    mapped_ids: List[str]
) -> float:
    """Calculate ID normalization success rate.
    
    Purpose: Distinguish retrieval failures from evaluation definition failures.
    
    Args:
        expected_ids: Original expected IDs from eval_questions.csv
        mapped_ids: Mapped IDs after ID normalization
        
    Returns:
        Success rate (0-1). < 0.9 indicates evaluation design issues.
    """
    if not expected_ids:
        return 1.0  # No expected IDs means no normalization needed
    
    # Count how many expected IDs were successfully mapped
    # (mapped_ids should contain all expected_ids after mapping)
    matched_count = len(set(expected_ids) & set(mapped_ids))
    
    # Also check if mapped_ids contains additional IDs (which is OK)
    # The key is: did we lose any expected IDs during mapping?
    success_rate = matched_count / len(expected_ids) if expected_ids else 1.0
    
    return success_rate


def calculate_multi_source_coverage(
    retrieved_ids: List[str],
    expected_sources: List[str]
) -> float:
    """Calculate multi-source coverage.
    
    Purpose: Check if enumeration questions retrieve from multiple sources.
    
    Args:
        retrieved_ids: List of retrieved document IDs
        expected_sources: List of expected source types (e.g., ["deal", "master"])
        
    Returns:
        Coverage ratio (0-1). Higher is better for multi-source questions.
    """
    if not expected_sources or len(expected_sources) <= 1:
        return 1.0  # Single-source questions don't need this metric
    
    # Extract source types from retrieved IDs
    retrieved_sources = set()
    for doc_id in retrieved_ids:
        if " p" in doc_id:  # PDF format: "filename.pdf p5"
            retrieved_sources.add("master")
        elif "_" in doc_id or doc_id.startswith("契約_") or doc_id.startswith("設備_"):  # Deal CSV intent
            retrieved_sources.add("deal")
    
    expected_sources_set = set(expected_sources)
    coverage = len(retrieved_sources & expected_sources_set) / len(expected_sources_set) if expected_sources_set else 1.0
    
    return coverage


def calculate_override_accuracy(
    retrieved_docs: List[Dict[str, Any]],
    expected_sources: List[str]
) -> float:
    """Calculate override accuracy for deal/master precedence.
    
    Purpose: Detect cases where master was used despite deal existing.
    
    Args:
        retrieved_docs: List of retrieved document metadata dicts (ordered)
        expected_sources: Expected sources for the question (e.g., ["deal"], ["deal","master"])
        
    Returns:
        Accuracy rate (0-1). Higher is better.
    """
    if not expected_sources:
        return 1.0

    expected = set(expected_sources)
    if "deal" not in expected:
        return 1.0  # Not an override question

    # If deal is expected, ensure the first source is deal
    if not retrieved_docs:
        return 0.0
    first_source = retrieved_docs[0].get("source_type")
    return 1.0 if first_source == "deal" else 0.0


def calculate_pdf_search_rate(
    retrieved_sources: List[str]
) -> float:
    """Calculate PDF search rate (master source usage)."""
    if not retrieved_sources:
        return 0.0
    return 1.0 if "master" in retrieved_sources else 0.0


# ============================================================================
# Generation Metrics (生成品質)
# ============================================================================


def is_template_only_response(summary_text: str) -> bool:
    """True when the reply leads with the legacy 'ask for inputs first' pattern.

    After Responder Rule 2 fix, KB body should precede this phrase; this flag
    tracks regressions where the summary still starts with the template line only.
    """
    t = (summary_text or "").strip()
    return t.startswith("以下の情報をお教えください")


def compute_intent_alignment(answer: Any) -> bool:
    """True when the top-ranked source intent matches the first evidence ID."""
    primary = getattr(answer, "primary_source_intent", None)
    ev = getattr(answer, "evidence", None) or []
    if not primary or not ev:
        return False
    return primary == ev[0]


def _fact_lookup_has_concrete_contact_hint(text: str) -> bool:
    """fact_lookup 用: 電話・URL・メールなど窓口の具体性があるか。"""
    if not text:
        return False
    return bool(
        re.search(r"\d{2,4}[-－\s]?\d{2,4}[-－\s]?\d{3,4}", text)
        or re.search(r"(?<!\d)\d{10,11}(?!\d)", text)
        or re.search(r"https?://", text, re.I)
        or re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    )


def _fact_lookup_has_organization_hint(text: str) -> bool:
    """電話なしでも、会社名等の窓口示唆があれば具体回答とみなす。"""
    if not text:
        return False
    return bool(re.search(r"(株式会社|有限会社|合資会社|合名会社|㈱|（株）)", text))


def _fact_lookup_is_vague_escape(summary_text: str) -> bool:
    """fact_lookup のみ: 曖昧逃げなら True（completeness を 0.5 に落とす対象）。

    「お問い合わせ」「確認」を単体では曖昧扱いしない（連絡先案内の正答を誤減点しない）。
    狭いパターン（詳細不明・情報不足・逃げ一文のみ等）に限定する。
    """
    s = (summary_text or "").strip()
    if not s:
        return True

    hint = _fact_lookup_has_concrete_contact_hint(s)
    org = _fact_lookup_has_organization_hint(s)

    if "詳細は不明" in s or "詳細は分かりません" in s:
        return True
    if "根拠情報が不足" in s or "情報が不足してい" in s:
        return True
    if "記載がありません" in s or "記載が確認できません" in s:
        return True

    # 短文: 具体ヒントがなければ減点（電話・会社名・十分な文量で救済）
    if len(s) < 20:
        if hint or org:
            return False
        return True

    # 契約書のみ案内で連絡先なし（短い逃げ）
    if "契約書をご確認ください" in s and len(s) < 120 and not hint:
        return True

    # 「お問い合わせください」系だけで窓口がない短い逃げ（複文・ある程度の文量は正答とみなす）
    if re.search(r"お問い合わせ[ください下さいいただけ]", s) and len(s) < 90:
        if hint or org:
            return False
        if len(s) >= 40:
            return False
        return True

    # 管理会社へ確認のみ（極短・電話・TEL なし）
    if (
        "管理会社" in s
        and "確認" in s
        and len(s) < 90
        and not hint
        and not re.search(r"TEL|電話|℡", s)
    ):
        if len(s) >= 40:
            return False
        if s.count("。") <= 1:
            return True

    return False


def calculate_answer_completeness(
    answer: "AnswerSchema",  # V2: AnswerSchema with items
    question_type: QuestionType,
    expected_items: Optional[int] = None
) -> float:
    """Calculate answer completeness score (V2: items数を直接参照).
    
    Args:
        answer: AnswerSchema (V2) with items
        question_type: Question type
        expected_items: Expected number of items/steps (optional)
        
    Returns:
        Completeness score (0.0, 0.5, 1.0)
    """
    # V2: items数を直接参照
    total_items = len(answer.items)
    
    if question_type == "policy_enumeration":
        if expected_items:
            if total_items >= expected_items:
                return 1.0
            elif total_items >= expected_items * 0.5:
                return 0.5
            else:
                return 0.0
        else:
            # Default: at least 3 items for enumeration
            if total_items >= 3:
                return 1.0
            elif total_items >= 1:
                return 0.5
            else:
                return 0.0
    
    elif question_type == "procedure":
        if expected_items:
            if total_items >= expected_items:
                return 1.0
            elif total_items >= expected_items * 0.5:
                return 0.5
            else:
                return 0.0
        else:
            # Default: at least 3 steps for procedure
            if total_items >= 3:
                return 1.0
            elif total_items >= 1:
                return 0.5
            else:
                return 0.0
    
    elif question_type == "fact_lookup":
        # Single clear answer expected (at least 1 item).
        # Vague penalty uses narrow patterns only; see _fact_lookup_is_vague_escape.
        if total_items >= 1:
            summary_text = answer.summary
            if _fact_lookup_is_vague_escape(summary_text):
                return 0.5
            # Bug 5w1: summary may be a generic intro while items contain explicit "記載なし".
            # Use narrow explicit patterns (not the full vague check) to avoid penalizing
            # short but factual item texts like "114,600円" or "第3条".
            _EXPLICIT_NOT_FOUND = (
                "記載が確認できません",
                "記載がありません",
                "記載が見当たりません",
                "確認できませんでした",
                "記載を確認できませんでした",
            )
            first_item_text = answer.items[0].text if answer.items else ""
            if any(p in first_item_text for p in _EXPLICIT_NOT_FOUND):
                return 0.5
            return 1.0
        else:
            return 0.0
    
    else:
        # For other types, default to 1.0 if has items
        return 1.0 if total_items >= 1 else 0.0


def calculate_evidence_binding_rate(
    answer: "AnswerSchema",  # V2: AnswerSchema with items
    question_type: QuestionType,
    evidence_ids: List[str]
) -> float:
    """Calculate evidence binding rate (V2: itemsのcitationを直接参照).
    
    V2のみ使用のため、itemsのcitationを直接参照する。
    これにより、どのメトリクスがどのフィールドを見るかが一貫する。
    
    Args:
        answer: AnswerSchema (V2) with items
        question_type: Question type
        evidence_ids: List of evidence/document IDs (for fallback)
        
    Returns:
        Binding rate (0-1). Target: policy_enumeration ≥ 0.8, procedure ≥ 0.7
    """
    if not answer.items:
        return 0.0
    
    # V2: itemsのcitationをチェック
    items_with_citation = sum(1 for item in answer.items if item.citation)
    return items_with_citation / len(answer.items)


def calculate_over_summarization_rate(
    answer_text: str,
    question_type: QuestionType,
    expected_items: Optional[int] = None
) -> float:
    """Calculate over-summarization rate.
    
    Purpose: Detect abstract answers that don't enumerate specific items.
    
    Args:
        answer_text: Generated answer text
        question_type: Question type
        expected_items: Expected number of items
        
    Returns:
        Over-summarization rate (0-1). Higher = more over-summarized.
    """
    if question_type not in ["policy_enumeration", "procedure"]:
        return 0.0  # Not applicable for other types
    
    # Abstract phrases that indicate over-summarization
    abstract_phrases = [
        "などが含まれます",
        "に関するものです",
        "一般的に",
    ]
    
    abstract_count = sum(1 for phrase in abstract_phrases if phrase in answer_text)
    
    # Count actual enumerated items
    numbered_items = len(re.findall(r'\d+[\.\)、]', answer_text))
    bullet_items = len(re.findall(r'[•・-]\s', answer_text))
    total_items = numbered_items + bullet_items
    
    # Over-summarization if abstract phrases present and few items enumerated
    if abstract_count > 0 and total_items < (expected_items or 3):
        return 1.0
    elif abstract_count > 0:
        return 0.5
    else:
        return 0.0


# ============================================================================
# Safety Metrics (安全・統制)
# ============================================================================

class SafetyEvaluationResult(BaseModel):
    """Result of safety evaluation (decomposed hallucination)."""
    relevance: float = Field(description="Relevance score (0-1)", ge=0.0, le=1.0)
    hallucination_fact_error: float = Field(description="Fact error rate (0-1, higher=worse)", ge=0.0, le=1.0)
    hallucination_unsourced_claim: float = Field(description="Unsourced claim rate (0-1, higher=worse)", ge=0.0, le=1.0)
    hallucination_overreach: float = Field(description="Overreach rate (0-1, higher=worse)", ge=0.0, le=1.0)


def llm_evaluate_answer_v2(
    question: str,
    context: str,
    answer: str,
    llm_model: str = "gpt-4o-mini"
) -> Dict[str, float]:
    """Evaluate answer using LLM v2 (decomposed hallucination).
    
    Args:
        question: User question
        context: Context/evidence used to generate the answer
        answer: Generated answer to evaluate
        llm_model: LLM model name to use for evaluation
        
    Returns:
        Dictionary with:
        - relevance: Relevance score (0-1)
        - hallucination_fact_error: Fact error rate (0-1, higher=worse)
        - hallucination_unsourced_claim: Unsourced claim rate (0-1, higher=worse)
        - hallucination_overreach: Overreach rate (0-1, higher=worse)
    """
    llm = init_chat_model(llm_model, model_provider="openai")
    llm_structured = llm.with_structured_output(SafetyEvaluationResult)
    
    evaluation_prompt = ChatPromptTemplate.from_template("""
質問: {question}

根拠情報（コンテキスト）:
{context}

評価対象の回答:
{answer}

以下の観点で評価してください：

1. **Relevance（関連性）**: 回答が質問に関連しているか、質問に適切に答えているか
   - 1.0: 完全に関連している、質問に正確に対応している
   - 0.5: 部分的に関連しているが、質問の一部にしか答えていない
   - 0.0: 関連性が低い、質問に答えていない

2. **Hallucination（幻覚）の3種類を分解して評価**:

   a. **fact_error（明確な虚偽）**: 根拠情報と明確に矛盾する事実が含まれているか
      - 1.0: 明確な虚偽が含まれている（悪い）
      - 0.5: 一部矛盾する可能性がある
      - 0.0: 虚偽は含まれていない（良い）

   b. **unsourced_claim（根拠なし断定）**: 根拠情報に記載されていない情報を断定しているか
      - 1.0: 多くの根拠なし断定が含まれている（悪い）
      - 0.5: 一部根拠なしの情報が含まれる
      - 0.0: すべて根拠に基づいている（良い）

   c. **overreach（証拠外推論）**: 根拠情報から推論を超えた主張をしているか
      - 1.0: 証拠外の推論が多い（悪い）
      - 0.5: 一部推論が過剰
      - 0.0: 適切な範囲内の推論（良い）

JSON形式で出力してください。
""")
    
    chain = evaluation_prompt | llm_structured
    
    try:
        result = chain.invoke({
            "question": question,
            "context": context,
            "answer": answer,
        })
        
        if isinstance(result, SafetyEvaluationResult):
            return {
                "relevance": result.relevance,
                "hallucination_fact_error": result.hallucination_fact_error,
                "hallucination_unsourced_claim": result.hallucination_unsourced_claim,
                "hallucination_overreach": result.hallucination_overreach,
            }
        elif isinstance(result, dict):
            return {
                "relevance": float(result.get("relevance", 0.0)),
                "hallucination_fact_error": float(result.get("hallucination_fact_error", 0.0)),
                "hallucination_unsourced_claim": float(result.get("hallucination_unsourced_claim", 0.0)),
                "hallucination_overreach": float(result.get("hallucination_overreach", 0.0)),
            }
        else:
            return {
                "relevance": 0.0,
                "hallucination_fact_error": 0.0,
                "hallucination_unsourced_claim": 0.0,
                "hallucination_overreach": 0.0,
            }
            
    except Exception as e:
        import sys
        print(f"Warning: LLM evaluation v2 failed: {e}", file=sys.stderr)
        return {
            "relevance": 0.0,
            "hallucination_fact_error": 0.0,
            "hallucination_unsourced_claim": 0.0,
            "hallucination_overreach": 0.0,
        }


def detect_prohibited_policy_v2(
    text: str,
    question: str,
    question_type: Optional[QuestionType] = None
) -> Dict[str, bool]:
    """Detect prohibited policy mention (v2, typed).
    
    Args:
        text: Answer text to check
        question: Original question
        question_type: Question type (for conditional evaluation)
        
    Returns:
        Dictionary with:
        - mentions_prohibited: Overall detection (for backward compatibility)
        - mentions_prohibited.confirmation: For policy_confirmation questions (lower is better)
        - mentions_prohibited.enumeration: For policy_enumeration questions (higher is better)
    """
    # Keywords that indicate questions about prohibited policies
    prohibited_question_keywords = [
        "ペット", "pet", "飼育", "動物",
        "禁止", "不可", "できない", "認められない",
    ]
    
    # Keywords that indicate prohibited policy in answer
    prohibited_answer_keywords = [
        "禁止", "不可", "できません", "認められません",
        "禁止されています", "禁止です", "禁止となっています",
    ]
    
    # Check if question is about prohibited policies
    is_prohibited_question = any(
        keyword in question.lower() for keyword in prohibited_question_keywords
    )
    
    if not is_prohibited_question:
        return {
            "mentions_prohibited": False,
            "mentions_prohibited.confirmation": False,
            "mentions_prohibited.enumeration": False,
        }
    
    # Check if answer mentions prohibited keywords
    mentions = any(keyword in text for keyword in prohibited_answer_keywords)
    
    result = {
        "mentions_prohibited": mentions,  # Backward compatibility
    }
    
    # Type-specific evaluation
    if question_type == "policy_confirmation":
        # For confirmation questions, lower is better (should mention if asked)
        result["mentions_prohibited.confirmation"] = mentions
    elif question_type == "policy_enumeration":
        # For enumeration questions, higher is better (should enumerate)
        result["mentions_prohibited.enumeration"] = mentions
    else:
        # For other types, use default behavior
        result["mentions_prohibited.confirmation"] = False
        result["mentions_prohibited.enumeration"] = False
    
    return result


# ============================================================================
# Legacy compatibility (for backward compatibility during transition)
# ============================================================================

def calculate_retrieval_metrics(
    retrieved_ids: List[str],
    expected_ids: List[str],
    k_values: List[int] = [5, 10]
) -> Dict[str, float]:
    """Legacy retrieval metrics (for backward compatibility).
    
    Use calculate_retrieval_metrics_v2() for new code.
    """
    return calculate_retrieval_metrics_v2(retrieved_ids, expected_ids, None, k_values)


def llm_evaluate_answer(
    question: str,
    context: str,
    answer: str,
    llm_model: str = "gpt-4o-mini"
) -> Dict[str, float]:
    """Legacy LLM evaluation (for backward compatibility).
    
    Use llm_evaluate_answer_v2() for new code.
    """
    result = llm_evaluate_answer_v2(question, context, answer, llm_model)
    # Convert to legacy format
    return {
        "relevance": result["relevance"],
        "hallucination": 1.0 - max(
            result["hallucination_fact_error"],
            result["hallucination_unsourced_claim"],
            result["hallucination_overreach"]
        ),  # Convert to factuality score (higher is better)
    }


def detect_prohibited_policy(text: str, question: str) -> bool:
    """Legacy prohibited policy detection (for backward compatibility).
    
    Use detect_prohibited_policy_v2() for new code.
    """
    result = detect_prohibited_policy_v2(text, question, None)
    return result["mentions_prohibited"]


# ============================================================================
# PII Detection (unchanged)
# ============================================================================

PII_PATTERN_NAMES = ("room_number", "phone", "email", "date")


def detect_pii(text: str) -> bool:
    """Detect PII (Personally Identifiable Information) in text using regex patterns.

    Args:
        text: Text to check for PII

    Returns:
        True if PII detected, False otherwise
    """
    return analyze_pii(text)["contains_pii"]


def analyze_pii(
    text: str,
    extra_allowlist_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Classify PII-related signals for evaluation (policy allowlist vs leak vs false-positive prone).

    Order: prefer splitting before changing regexes (plan: scoring policy first).
    extra_allowlist_patterns: optional regex strings from config (RAG_OFFICIAL_CONTACT_PATTERNS).
    """
    patterns = [
        (PII_PATTERN_NAMES[0], r"\d{1,4}号室"),
        (PII_PATTERN_NAMES[1], r"0\d{1,4}-\d{1,4}-\d{4}"),
        (PII_PATTERN_NAMES[2], r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        (PII_PATTERN_NAMES[3], r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"),
    ]
    pii_reasons: List[str] = []
    matched_name: set[str] = set()
    for name, pattern in patterns:
        if re.search(pattern, text):
            matched_name.add(name)
            pii_reasons.append(name)

    # Official / operational numbers published in KB (not counted as leak)
    policy_phone_patterns = [
        r"0978-68-1588",  # To You
        r"0978-68-0315",  # ダイプロ
        r"0120-761-378",  # 九州電力
        r"097-542-1121",  # J:COM
        r"0978-72-5197",  # 国東市水道
    ]
    for p in extra_allowlist_patterns or []:
        p = p.strip()
        if p:
            policy_phone_patterns.append(p)
    policy_allowed_contact = any(re.search(p, text) for p in policy_phone_patterns)

    phone_matched = "phone" in matched_name
    room_matched = "room_number" in matched_name
    email_matched = "email" in matched_name
    date_matched = "date" in matched_name

    # Heuristic: room / personal email = suspected leak; FAQ phone alone = policy
    pii_true_leak_suspected = bool(room_matched or email_matched)
    pii_false_positive_prone = bool(date_matched and not room_matched and not email_matched)

    contains_pii = bool(matched_name)

    return {
        "contains_pii": contains_pii,
        "pii_reasons": pii_reasons,
        "pii_policy_allowed_contact": policy_allowed_contact and phone_matched and not pii_true_leak_suspected,
        "pii_true_leak_suspected": pii_true_leak_suspected,
        "pii_false_positive_prone": pii_false_positive_prone,
    }
