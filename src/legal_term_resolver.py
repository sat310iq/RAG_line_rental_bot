"""Legal term resolver for RAG answerer.

回答テキストまたは根拠チャンクに含まれる法律・不動産用語を検出し、
平易な説明をプロンプトに注入するためのモジュール。

Usage:
    resolver = LegalTermResolver.from_default()
    injection = resolver.build_prompt_injection(answer_text)
    # injection が空文字でなければプロンプトに追記する
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

DEFAULT_DICT_PATH = Path(__file__).parent.parent / "data" / "legal_terms_dict.yaml"


@dataclass
class LegalTerm:
    word: str
    plain: str
    context: Optional[str] = None
    aliases: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if self.aliases is None:
            self.aliases = []


class LegalTermResolver:
    def __init__(self, terms: List[LegalTerm]) -> None:
        self._terms = terms

    @classmethod
    def from_path(cls, path: Path) -> "LegalTermResolver":
        """YAMLファイルから辞書を読み込む。"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        terms = [
            LegalTerm(
                word=entry["word"],
                plain=entry["plain"],
                context=entry.get("context"),
                aliases=entry.get("aliases", []),
            )
            for entry in data.get("terms", [])
        ]
        return cls(terms)

    @classmethod
    def from_default(cls) -> "LegalTermResolver":
        """デフォルトの辞書パスから読み込む。"""
        return cls.from_path(DEFAULT_DICT_PATH)

    def detect(self, text: str) -> List[LegalTerm]:
        """テキストに含まれる法律用語を検出して返す。

        長い語を優先して検出し、部分一致による重複を防ぐ。
        例: 「将来抵当権」が検出済みなら「抵当権」はスキップする。
        """
        sorted_terms = sorted(self._terms, key=lambda t: len(t.word), reverse=True)

        matched_chars: set[str] = set()
        seen_words: set[str] = set()
        matched: list[LegalTerm] = []

        for term in sorted_terms:
            search_targets = [term.word] + list(term.aliases or [])
            hit = any(target in text for target in search_targets)
            if not hit:
                continue
            if any(term.word in mc for mc in matched_chars):
                continue
            if term.word not in seen_words:
                seen_words.add(term.word)
                matched_chars.add(term.word)
                matched.append(term)

        word_order = {t.word: i for i, t in enumerate(self._terms)}
        matched.sort(key=lambda t: word_order.get(t.word, 999))
        return matched

    def build_prompt_injection(self, text: str) -> str:
        """検出した用語の平易な説明をプロンプト注入用文字列として返す。

        マッチがなければ空文字を返す。
        """
        matched = self.detect(text)
        if not matched:
            return ""

        lines = ["【用語の平易な説明】（回答時に参考にしてください）"]
        for term in matched:
            line = f"- {term.word}: {term.plain}"
            if term.context:
                line += f"（{term.context}）"
            lines.append(line)
        return "\n".join(lines)
