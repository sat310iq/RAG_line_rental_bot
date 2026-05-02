"""Helpers for offline / integration evaluation of structured RAG answers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.rag_answerer import AnswerSchema


def answer_body_text(answer: AnswerSchema) -> str:
    """Text used for keyword checks: summary + item texts only (not B2 template footers)."""
    parts: List[str] = []
    if answer.summary:
        parts.append(str(answer.summary).strip())
    for it in answer.items or []:
        if it.text:
            parts.append(str(it.text).strip())
    return "\n".join(parts)


def parse_semicolon_list(val: Any) -> List[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [p.strip() for p in val.replace(",", ";").split(";") if p.strip()]
    return [str(x).strip() for x in val if str(x).strip()]


def _required_keyword_groups(case: Dict[str, Any]) -> Optional[List[List[str]]]:
    """If case uses any_of schema, return list of keyword groups; else None."""
    rk = case.get("required_keywords")
    if isinstance(rk, dict):
        groups = rk.get("any_of") or rk.get("anyOf")
        if groups and isinstance(groups, list):
            out: List[List[str]] = []
            for grp in groups:
                if isinstance(grp, (list, tuple)):
                    out.append([str(k).strip() for k in grp if str(k).strip()])
                elif isinstance(grp, str) and grp.strip():
                    out.append(parse_semicolon_list(grp))
            return out or None
    return None


def default_required_keywords(case: Dict[str, Any]) -> List[str]:
    """AND list for legacy cases (not any_of). Empty when any_of is used."""
    if _required_keyword_groups(case) is not None:
        return []
    if case.get("required_keywords"):
        val = case["required_keywords"]
        if isinstance(val, dict):
            return []
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        return parse_semicolon_list(val)
    snippets = case.get("expected_snippets") or []
    if len(snippets) >= 2:
        return [str(snippets[0]), str(snippets[1])]
    if snippets:
        return [str(snippets[0])]
    return []


def required_keyword_pass(case: Dict[str, Any], body: str) -> bool:
    """True if required keyword constraints are satisfied (any_of OR legacy AND)."""
    groups = _required_keyword_groups(case)
    if groups is not None:
        if not groups:
            return True
        for grp in groups:
            if not grp:
                continue
            if all((kw in body) for kw in grp):
                return True
        return False
    required = default_required_keywords(case)
    return all((not r) or (r in body) for r in required)


def merged_forbidden_keywords(case: Dict[str, Any], eval_defaults: Optional[Dict[str, Any]]) -> List[str]:
    base = parse_semicolon_list((eval_defaults or {}).get("forbidden_keywords"))
    base.extend(parse_semicolon_list(case.get("forbidden_keywords")))
    seen: set[str] = set()
    out: List[str] = []
    for s in base:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def keyword_eval_flags(
    answer: AnswerSchema,
    case: Dict[str, Any],
    eval_defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return required_ok / forbidden_ok against answer body (summary + items)."""
    body = answer_body_text(answer)
    groups = _required_keyword_groups(case)
    if groups is not None:
        req_display = " |OR| ".join(";".join(g) for g in groups)
    else:
        req_display = ";".join(default_required_keywords(case))
    forbidden = merged_forbidden_keywords(case, eval_defaults)
    required_ok = required_keyword_pass(case, body)
    forbidden_ok = all((not f) or (f not in body) for f in forbidden)
    return {
        "required_ok": required_ok,
        "forbidden_ok": forbidden_ok,
        "required_keywords": req_display,
        "forbidden_checked": ";".join(forbidden),
    }
