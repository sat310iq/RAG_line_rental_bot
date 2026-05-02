#!/usr/bin/env python3
"""Build top-N failure backlog JSONL + summary Markdown from run_eval JSONL.

Extends `wrong_intent_match` with heuristics not always present in `infer_failure_tags`.
See docs/eval.md for D-group / forced-leg vs `auto` router KPI caveats.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Primary failure signals for backlog inclusion (per plan)
BACKLOG_TAG_ORDER = (
    "should_escalate_but_answered",
    "wrong_intent_match",
    "needs_clarification",
    "overbroad_rule",
)

PREVIEW_MAX = 280


def _root() -> Path:
    return PROJECT_ROOT


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def get_mode(rec: Dict[str, Any]) -> str:
    dt = rec.get("debug_trace")
    if isinstance(dt, dict) and dt.get("mode"):
        return str(dt["mode"])
    return str(rec.get("mode") or "unknown")


def extended_wrong_intent_match(question: str, answer: str) -> bool:
    """Heuristics beyond run_eval.infer_failure_tags; backlog-only."""
    q = question or ""
    a = answer or ""
    if "ガス料金" in a and any(t in q for t in ("家賃", "減額", "喫煙", "清掃")):
        return True
    if any(t in q for t in ("家賃", "減額", "減額請求")) and ("ガス" in a and "料金" in a):
        return True
    if any(t in q for t in ("喫煙", "タバコ", "たばこ")) and ("ガス料金" in a or "ガス代" in a):
        return True
    if "清掃" in q and ("ゴミ" in a or "ゴミステーション" in a or "ゴミ出し" in a):
        return True
    if "水漏れ" in q and "ガス" in a and "料金" in a:
        return True
    return False


def merge_failure_tags(rec: Dict[str, Any]) -> List[str]:
    raw = rec.get("failure_tags")
    if isinstance(raw, list):
        tags = [str(t).strip() for t in raw if str(t).strip()]
    else:
        tags = []
    q = str(rec.get("question") or "")
    a = str(rec.get("answer") or "")
    if extended_wrong_intent_match(q, a) and "wrong_intent_match" not in tags:
        tags.append("wrong_intent_match")
    return sorted(set(tags))


def pick_primary_tag(tags: List[str]) -> str:
    s = set(tags)
    for t in BACKLOG_TAG_ORDER:
        if t in s:
            return t
    return tags[0] if tags else "unknown"


def wrong_intent_is_p0(question: str, answer: str) -> bool:
    q, a = question or "", answer or ""
    if "ガス料金" in a and any(
        t in q for t in ("家賃", "減額", "喫煙", "清掃", "タバコ", "たばこ")
    ):
        return True
    if any(t in q for t in ("家賃", "減額")) and "ガス" in a:
        return True
    return False


def assign_priority(
    tags: Set[str], mode: str, question: str, answer: str
) -> Tuple[str, int]:
    """Return (P0|P1|P2, numeric for sort: lower = higher priority)."""
    if "should_escalate_but_answered" in tags and mode == "auto":
        return "P0", 0
    if "wrong_intent_match" in tags and wrong_intent_is_p0(question, answer):
        return "P0", 0
    if "overbroad_rule" in tags or "needs_clarification" in tags:
        return "P1", 1
    if "should_escalate_but_answered" in tags and mode in ("kb_only", "rag"):
        return "P2", 2
    if "wrong_intent_match" in tags:
        return "P1", 1
    return "P2", 2


def classify_backlog_item(
    rec: Dict[str, Any], merged_tags: List[str], primary: str, mode: str
) -> Tuple[str, str, str]:
    """root_cause, fix_type, suggested_change."""
    q = str(rec.get("question") or "")
    a = str(rec.get("answer") or "")

    if primary == "should_escalate_but_answered":
        if mode in ("kb_only", "rag"):
            return (
                "forced_leg_bypasses_auto_escalation",
                "evaluation_scope",
                "Router KPI では `auto` 実行を正とし、`kb_only`/`rag` 強制 leg の D 群は品質スコアから除外するか、別タグ（forced_leg_mismatch）で扱う。",
            )
        if mode == "auto":
            return (
                "missing_escalation_pattern",
                "escalation_pattern",
                "src/management_escalation.py およびルール系でエスカレーション検知語句を追加し、expected_route=escalation に寄せる。",
            )
        return (
            "escalation_not_applied_in_forced_leg",
            "evaluation_policy_or_auto_only_note",
            "expected_route と actual_route の差分を `auto` 専用実行で再確認。",
        )

    if primary == "wrong_intent_match":
        return (
            "category_mismatch_answer",
            "negative_keyword",
            "faq_kb.csv: 意図ずれのある intent へ negative_keywords / exclude_keywords 追加（例: ガス料金 intent に 家賃・減額・喫煙、ゴミ系に 清掃費）。keyword_override 条件の見直し。",
        )

    if primary == "needs_clarification":
        return (
            "offline_harness_cannot_reproduce_line_state",
            "clarification_pattern",
            "曖昧パターン（例: 水道の件/修繕/契約/更新）を CSV か別リストに登録。LINE 実機の clarification を別評価に切り出す。",
        )

    if primary == "overbroad_rule":
        return (
            "template_subject_mismatch",
            "negative_keyword",
            "exclude_keywords / negative_keywords を厳格化し、主語違いの Rule 当たりを防ぐ。",
        )

    return (
        "unknown",
        "dataset_label",
        "手元で要因を確認。",
    )


def default_input_path() -> Path:
    runs = _root() / "eval" / "runs"
    if not runs.is_dir():
        return Path()
    cands = sorted(
        runs.glob("ab_compare_*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not cands:
        cands = sorted(
            runs.glob("run_*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    return cands[0] if cands else Path()


def failure_tag_counts_all(rows: List[Dict[str, Any]]) -> Counter:
    c: Counter = Counter()
    for rec in rows:
        for t in merge_failure_tags(rec):
            c[t] += 1
    return c


def build_backlog_rows(
    rows: List[Dict[str, Any]], top_n: int
) -> List[Dict[str, Any]]:
    backlog_tags: Set[str] = set(BACKLOG_TAG_ORDER)
    candidates: List[Dict[str, Any]] = []

    for rec in rows:
        merged = merge_failure_tags(rec)
        if not set(merged) & backlog_tags:
            continue
        mode = get_mode(rec)
        pri, pri_n = assign_priority(
            set(merged), mode, str(rec.get("question") or ""), str(rec.get("answer") or "")
        )
        primary = pick_primary_tag(merged)
        root_cause, fix_type, suggested = classify_backlog_item(
            rec, merged, primary, mode
        )
        ans = str(rec.get("answer") or "")
        preview = ans[:PREVIEW_MAX] + ("…" if len(ans) > PREVIEW_MAX else "")
        candidates.append(
            {
                "_pri_n": pri_n,
                "_pri_label": pri,
                "_primary": primary,
                "question": str(rec.get("question") or ""),
                "ab_group": str(rec.get("ab_group") or "").strip() or None,
                "mode": mode,
                "expected_route": str(rec.get("expected_route") or ""),
                "actual_route": str(rec.get("actual_route") or ""),
                "failure_tags": merged,
                "answer_preview": preview,
                "root_cause": root_cause,
                "fix_type": fix_type,
                "suggested_change": suggested,
                "priority": pri,
            }
        )

    order_idx = {t: i for i, t in enumerate(BACKLOG_TAG_ORDER)}

    def _tag_order(primary: str) -> int:
        return order_idx.get(primary, 99)

    candidates.sort(
        key=lambda r: (
            r["_pri_n"],
            _tag_order(r.get("_primary", "")),
            r.get("question", ""),
            r.get("mode", ""),
        )
    )
    out: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates[: top_n], 1):
        item = {k: v for k, v in c.items() if not k.startswith("_")}
        item["rank"] = i
        out.append(item)
    return out


def write_summary_md(
    path: Path,
    input_path: Path,
    top_items: List[Dict[str, Any]],
    all_rows: List[Dict[str, Any]],
    top_n: int,
) -> None:
    tag_c = failure_tag_counts_all(all_rows)
    top_tags = tag_c.most_common(20)
    run_id = str(all_rows[0].get("run_id", "")) if all_rows else ""

    lines: List[str] = [
        "# Failure Backlog Summary",
        "",
        f"Generated from: `{input_path.name}` (run_id={run_id or 'n/a'})",
        f"Backlog size: {len(top_items)} (cap={top_n}).",
        "",
        "Extended `wrong_intent_match` heuristics are applied in this script; tags may not match raw JSONL alone.",
        "",
        "## Router KPI vs forced legs (important)",
        "",
        "- **D-group** questions may show management-company guidance when evaluated with the **`auto`** path (including D-group extra runs in `run_eval.py`).",
        "- The same question under **`kb_only` or `rag` forced** modes uses the standard pipeline; mismatches there are a **separate** quality issue from Router KPI and `should_escalate_but_answered` on `auto`.",
        "- Treat **Router KPI** (auto) and **forced-leg quality** (kb_only/rag) on different scorecards, or tag forced-leg rows as `evaluation_scope` fixes.",
        "",
        "## Top failure tags (merged, all rows)",
        "",
    ]
    for t, n in top_tags:
        lines.append(f"- `{t}`: {n}")
    if not top_tags:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## Top backlog items",
            "",
            "| rank | question | tag | root_cause | fix_type | suggested_change |",
            "|---|---|---|---|---|---|",
        ]
    )
    for it in top_items:
        q = (it.get("question") or "").replace("|", "\\|")
        if len(q) > 60:
            q = q[:57] + "..."
        tag = (pick_primary_tag(list(it.get("failure_tags") or [])) or "").replace(
            "|", "\\|"
        )
        rc = (it.get("root_cause") or "").replace("|", "\\|")
        if len(rc) > 40:
            rc = rc[:37] + "..."
        ft = (it.get("fix_type") or "").replace("|", "\\|")
        su = (it.get("suggested_change") or "").replace("|", "\\|")
        if len(su) > 50:
            su = su[:47] + "..."
        lines.append(
            f"| {it.get('rank')} | {q} | {tag} | {rc} | {ft} | {su} |"
        )

    lines.extend(
        [
            "",
            "## Recommended next commit (max 3)",
            "",
            "1. Tighten **negative / exclude keywords** (gas/water/garbage/repair intents) for wrong_intent and overbroad_rule.",
            "2. Register **ambiguous phrasing** (水道口頭/修繕/契約/更新) for clarification or KB routing.",
            "3. **Scope evaluation** for D-group: separate `auto` Router KPI from `kb_only`/`rag` forced-leg notes in reports.",
        ]
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build top-N failure backlog from run_eval JSONL"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to ab_compare_*.jsonl (default: latest in eval/runs/)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Max backlog rows (default: 10)",
    )
    parser.add_argument(
        "--jsonl-out",
        type=Path,
        default=None,
        help="Output JSONL (default: data/eval/failure_backlog_top10.jsonl)",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=None,
        help="Output Markdown (default: data/eval/failure_backlog_summary.md)",
    )
    args = parser.parse_args()
    root = _root()
    in_path = args.input
    if in_path is None:
        in_path = default_input_path()
    elif not in_path.is_absolute():
        in_path = root / in_path
    if not in_path or not in_path.is_file():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    rows = load_jsonl(in_path)
    if not rows:
        print("Empty input.", file=sys.stderr)
        return 1

    top_n = max(1, int(args.top))
    backlog = build_backlog_rows(rows, top_n)
    jout = args.jsonl_out or (root / "data" / "eval" / "failure_backlog_top10.jsonl")
    mout = args.md_out or (root / "data" / "eval" / "failure_backlog_summary.md")
    if not jout.is_absolute():
        jout = root / jout
    if not mout.is_absolute():
        mout = root / mout
    jout.parent.mkdir(parents=True, exist_ok=True)
    with open(jout, "w", encoding="utf-8") as f:
        for it in backlog:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    write_summary_md(mout, in_path, backlog, rows, top_n)
    print(f"Wrote {len(backlog)} items -> {jout}")
    print(f"Wrote summary -> {mout}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
