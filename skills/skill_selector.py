from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    # rental_rag_poc/skills/skill_selector.py -> rental_rag_poc/
    return Path(__file__).resolve().parents[1]


def _normalize_triggers(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [str(raw)]
    return [str(item) for item in raw]


def _parse_frontmatter(skill_md_path: Path) -> dict[str, Any] | None:
    text = skill_md_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n?", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        print(
            f"[WARN] failed to parse frontmatter: {skill_md_path} ({exc})",
            file=sys.stderr,
        )
        return None
    if not isinstance(data, dict):
        return None
    return data


def _load_registry_entries() -> list[dict[str, Any]]:
    root = _repo_root()
    registry_path = root / "skills" / "registry.yaml"
    if not registry_path.exists():
        raise FileNotFoundError(f"registry not found: {registry_path}")

    loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        return []

    entries: list[dict[str, Any]] = []
    for section_entries in loaded.values():
        if not isinstance(section_entries, list):
            continue
        for entry in section_entries:
            if isinstance(entry, dict):
                entries.append(dict(entry))
    return entries


def _resolve_triggers(entry: dict[str, Any]) -> list[str]:
    triggers = _normalize_triggers(entry.get("triggers"))
    if triggers:
        return triggers

    root = _repo_root()
    path = entry.get("path")
    if not isinstance(path, str):
        return []
    skill_md = root / path / "SKILL.md"
    if not skill_md.exists():
        return []

    frontmatter = _parse_frontmatter(skill_md)
    if frontmatter is None:
        return []
    return _normalize_triggers(frontmatter.get("triggers"))


def select(query: str, scope: str | None = None) -> list[dict]:
    """
    Returns:
        [
            {
                "name": "contract_qa_skill",
                "path": "skills/rental_rag/contract_qa_skill",
                "scope": "rental_rag_only",
                "type": "task",
                "description": "...",
                "matched_triggers": ["契約", "QA"],
            },
            ...
        ]
    """
    query_lower = query.lower()
    results: list[dict[str, Any]] = []

    for entry in _load_registry_entries():
        if scope is not None and entry.get("scope") != scope:
            continue

        triggers = _resolve_triggers(entry)
        if not triggers:
            continue

        matched = [t for t in triggers if str(t).lower() in query_lower]
        if not matched:
            continue

        results.append(
            {
                "name": entry.get("name"),
                "path": entry.get("path"),
                "scope": entry.get("scope"),
                "type": entry.get("type"),
                "description": entry.get("description"),
                "matched_triggers": matched,
            }
        )

    results.sort(key=lambda item: len(item["matched_triggers"]), reverse=True)
    return results
