#!/usr/bin/env python3
"""Load skill metadata and update .cursorrules skill section."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SKILLS_START = "<!-- SKILLS_START -->"
SKILLS_END = "<!-- SKILLS_END -->"


@dataclass(frozen=True)
class SkillRecord:
    section: str
    name: str
    path: str
    scope: str
    type: str
    description: str
    triggers: list[str]


@dataclass(frozen=True)
class SkillDoc:
    path: str
    name: str | None
    description: str | None
    triggers: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load skills metadata from registry.yaml and SKILL.md files."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview markdown to stdout")
    parser.add_argument("--scope", help="Filter by scope value in registry.yaml")
    parser.add_argument(
        "--output",
        help="Output path for rules file. Default is <repo_root>/.cursorrules",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate registry vs SKILL.md mapping and print results",
    )
    return parser.parse_args()


def normalize_triggers(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [str(raw)]
    return [str(item) for item in raw]


def load_registry(registry_path: Path) -> tuple[list[str], dict[str, SkillRecord]]:
    if not registry_path.exists():
        print(f"[ERROR] registry file not found: {registry_path}", file=sys.stderr)
        raise SystemExit(1)

    try:
        loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[ERROR] failed to parse registry.yaml: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not isinstance(loaded, dict):
        print("[ERROR] registry.yaml must be a mapping", file=sys.stderr)
        raise SystemExit(1)

    sections: list[str] = []
    by_path: dict[str, SkillRecord] = {}

    for section_name, entries in loaded.items():
        if not isinstance(entries, list):
            print(
                f"[ERROR] registry section '{section_name}' must be a list",
                file=sys.stderr,
            )
            raise SystemExit(1)
        sections.append(str(section_name))
        for entry in entries:
            if not isinstance(entry, dict):
                print(
                    f"[ERROR] registry section '{section_name}' contains non-mapping entry",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            required = ["name", "path", "scope", "type", "description"]
            missing = [k for k in required if k not in entry]
            if missing:
                print(
                    "[ERROR] registry entry missing required fields "
                    f"{missing}: {entry}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            rel_path = str(entry["path"]).strip().replace("\\", "/")
            if rel_path in by_path:
                print(
                    f"[ERROR] duplicate registry path: {rel_path}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            by_path[rel_path] = SkillRecord(
                section=str(section_name),
                name=str(entry["name"]),
                path=rel_path,
                scope=str(entry["scope"]),
                type=str(entry["type"]),
                description=str(entry["description"]).strip(),
                triggers=normalize_triggers(entry.get("triggers")),
            )
    return sections, by_path


def parse_frontmatter(skill_md_path: Path, repo_root: Path) -> SkillDoc | None:
    text = skill_md_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n?", text, flags=re.DOTALL)
    if not match:
        print(
            f"[WARN] {skill_md_path}: frontmatter not found, skipped",
            file=sys.stderr,
        )
        return None
    yaml_block = match.group(1)
    try:
        frontmatter = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as exc:
        print(
            f"[WARN] {skill_md_path}: frontmatter parse failed, skipped ({exc})",
            file=sys.stderr,
        )
        return None
    if not isinstance(frontmatter, dict):
        print(
            f"[WARN] {skill_md_path}: frontmatter is not a mapping, skipped",
            file=sys.stderr,
        )
        return None

    skill_dir_rel = skill_md_path.parent.relative_to(repo_root).as_posix()
    return SkillDoc(
        path=skill_dir_rel,
        name=str(frontmatter.get("name")) if frontmatter.get("name") is not None else None,
        description=(
            str(frontmatter.get("description"))
            if frontmatter.get("description") is not None
            else None
        ),
        triggers=normalize_triggers(frontmatter.get("triggers")),
    )


def scan_skill_docs(skills_dir: Path, repo_root: Path) -> dict[str, SkillDoc]:
    docs: dict[str, SkillDoc] = {}
    for skill_md in sorted(skills_dir.glob("**/SKILL.md")):
        doc = parse_frontmatter(skill_md, repo_root=repo_root)
        if doc is None:
            continue
        docs[doc.path] = doc
    return docs


def compare_triggers(left: list[str], right: list[str]) -> bool:
    return sorted(left) == sorted(right)


def validate_registry(
    registry_by_path: dict[str, SkillRecord],
    docs_by_path: dict[str, SkillDoc],
) -> tuple[list[SkillRecord], list[tuple[SkillRecord, SkillDoc]], list[SkillRecord]]:
    ok: list[SkillRecord] = []
    warn: list[tuple[SkillRecord, SkillDoc]] = []
    miss: list[SkillRecord] = []

    for path, reg in registry_by_path.items():
        doc = docs_by_path.get(path)
        if doc is None:
            miss.append(reg)
            continue
        ok.append(reg)
        if not compare_triggers(doc.triggers, reg.triggers):
            warn.append((reg, doc))
    return ok, warn, miss


def warn_unregistered_skills(
    docs_by_path: dict[str, SkillDoc],
    registry_by_path: dict[str, SkillRecord],
) -> None:
    for path in sorted(docs_by_path.keys()):
        if path not in registry_by_path:
            print(
                f"[WARN] {path}: found SKILL.md but no registry entry, skipped",
                file=sys.stderr,
            )


def print_validate_report(
    ok: list[SkillRecord],
    warn: list[tuple[SkillRecord, SkillDoc]],
    miss: list[SkillRecord],
) -> None:
    for record in sorted(ok, key=lambda x: x.path):
        print(f"[OK]   {record.path}")
    for record, doc in sorted(warn, key=lambda x: x[0].path):
        print(f"[WARN] {record.path}: triggers mismatch")
        print(f"       SKILL.md : {doc.triggers}")
        print(f"       registry : {record.triggers}")
    for record in sorted(miss, key=lambda x: x.path):
        print(f"[MISS] registry entry '{record.name}' has no matching SKILL.md")


def section_heading(section_name: str) -> str:
    if section_name == "shared":
        return "_shared"
    return section_name


def generate_skills_section(
    sections: list[str],
    registry_by_path: dict[str, SkillRecord],
    docs_by_path: dict[str, SkillDoc],
    scope_filter: str | None,
) -> str:
    grouped: dict[str, list[SkillRecord]] = {section: [] for section in sections}
    for path, doc in docs_by_path.items():
        reg = registry_by_path.get(path)
        if reg is None:
            print(
                f"[WARN] {path}: found SKILL.md but no registry entry, skipped",
                file=sys.stderr,
            )
            continue
        if scope_filter and reg.scope != scope_filter:
            continue
        grouped.setdefault(reg.section, []).append(reg)

    lines: list[str] = [
        SKILLS_START,
        "",
        "## Available Skills",
        "",
        "> triggers は各 SKILL.md frontmatter が正。registry.yaml の triggers は転写。差異がある場合は SKILL.md 側を使う。",
        "",
    ]

    for section in sections:
        records = sorted(grouped.get(section, []), key=lambda x: x.name)
        if not records:
            continue
        lines.append(f"### {section_heading(section)}")
        lines.append("")
        lines.append("| Skill | Type | Description |")
        lines.append("|---|---|---|")
        for record in records:
            description = " ".join(record.description.split())
            lines.append(f"| {record.name} | {record.type} | {description} |")
        lines.append("")

    lines.append(SKILLS_END)
    lines.append("")
    return "\n".join(lines)


def update_cursorrules_file(output_path: Path, skills_block: str) -> bool:
    if output_path.exists():
        current = output_path.read_text(encoding="utf-8")
    else:
        current = ""

    start_exists = SKILLS_START in current
    end_exists = SKILLS_END in current

    if start_exists != end_exists:
        print(
            "[ERROR] .cursorrules contains only one of SKILLS_START/SKILLS_END markers",
            file=sys.stderr,
        )
        return False

    if start_exists and end_exists:
        pattern = re.compile(
            re.escape(SKILLS_START) + r".*?" + re.escape(SKILLS_END) + r"\n?",
            flags=re.DOTALL,
        )
        updated = pattern.sub(skills_block, current, count=1)
    else:
        suffix = "" if not current or current.endswith("\n") else "\n"
        updated = f"{current}{suffix}\n{skills_block}" if current else skills_block

    output_path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()

    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent
    skills_dir = repo_root / "skills"
    registry_path = skills_dir / "registry.yaml"

    sections, registry_by_path = load_registry(registry_path)
    docs_by_path = scan_skill_docs(skills_dir, repo_root=repo_root)

    ok, warn, miss = validate_registry(registry_by_path, docs_by_path)
    if args.validate:
        print_validate_report(ok, warn, miss)

    output_path = (
        Path(args.output).expanduser()
        if args.output
        else repo_root / ".cursorrules"
    )

    should_render = not args.validate or args.dry_run
    if should_render:
        skills_block = generate_skills_section(
            sections=sections,
            registry_by_path=registry_by_path,
            docs_by_path=docs_by_path,
            scope_filter=args.scope,
        )
        if args.dry_run:
            print(skills_block)
        else:
            ok_write = update_cursorrules_file(output_path, skills_block)
            if not ok_write:
                return 1

    if miss:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
