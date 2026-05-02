from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


def repo_root() -> Path:
    # rental_rag_poc/skills/tests/test_skill_regression.py -> rental_rag_poc/
    return Path(__file__).resolve().parents[2]


def load_cases() -> list[dict]:
    path = repo_root() / "skills" / "tests" / "cases.jsonl"
    cases: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


def load_registry() -> tuple[dict[str, dict], dict[str, str]]:
    registry_path = repo_root() / "skills" / "registry.yaml"
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    by_name: dict[str, dict] = {}
    path_by_name: dict[str, str] = {}
    for section_items in data.values():
        for item in section_items:
            by_name[item["name"]] = item
            path_by_name[item["name"]] = item["path"]
    return by_name, path_by_name


def extract_procedure_text(skill_md_text: str) -> str:
    pattern = re.compile(
        r"^## Procedure\s*(.*?)^\s*##\s+",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(skill_md_text + "\n## END\n")
    if not match:
        return ""
    return match.group(1).strip()


def normalize_text(text: str) -> str:
    return re.sub(r"[\s`*_\-:：・/()\[\]{}。，、。]", "", text).lower()


def contains_as_subsequence(keyword: str, text: str) -> bool:
    """Allow non-contiguous matching for combined labels like 'スコープ確認'."""
    k = normalize_text(keyword)
    t = normalize_text(text)
    if not k:
        return True
    if k in t:
        return True
    for candidate in keyword_candidates(k):
        if candidate in t:
            return True
        i = 0
        for ch in t:
            if i < len(candidate) and ch == candidate[i]:
                i += 1
            if i == len(candidate):
                return True
    return False


def keyword_candidates(normalized_keyword: str) -> list[str]:
    candidates: list[str] = [normalized_keyword]
    # ケース定義側の語尾（確認/方針）や表現差（可能な）を許容
    for suffix in ("確認", "方針"):
        if normalized_keyword.endswith(suffix):
            candidates.append(normalized_keyword[: -len(suffix)])
    if "可能な" in normalized_keyword:
        candidates.append(normalized_keyword.replace("可能な", ""))
    if "品質ゲート" in normalized_keyword:
        candidates.append("qualitygate")
    return [c for c in candidates if c]


def test_registry_has_all_case_skills() -> None:
    cases = load_cases()
    registry_by_name, _ = load_registry()
    missing = [c["skill"] for c in cases if c["skill"] not in registry_by_name]
    assert not missing, f"skills missing in registry.yaml: {missing}"


def test_refs_exist_from_repo_root() -> None:
    root = repo_root()
    cases = load_cases()
    missing_refs: list[str] = []
    for case in cases:
        for ref in case["expect"]["refs"]:
            if not (root / ref).exists():
                missing_refs.append(ref)
    assert not missing_refs, f"missing referenced files: {missing_refs}"


def test_outputs_keywords_exist_in_procedure() -> None:
    root = repo_root()
    cases = load_cases()
    _, path_by_name = load_registry()
    missing_keywords: list[str] = []

    for case in cases:
        skill = case["skill"]
        skill_path = path_by_name[skill]
        skill_md = root / skill_path / "SKILL.md"
        procedure_text = extract_procedure_text(skill_md.read_text(encoding="utf-8"))
        for keyword in case["expect"]["outputs"]:
            if not contains_as_subsequence(keyword, procedure_text):
                missing_keywords.append(f"{skill}: {keyword}")

    assert (
        not missing_keywords
    ), f"keywords not found in corresponding Procedure section: {missing_keywords}"
