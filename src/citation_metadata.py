"""Structured citation metadata for contract chunks (条・項)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# Lines like "2 前項の…" / "3 甲及び乙" (項番号は1–2桁の半角・全角数字)
_PARA_START_RE = re.compile(
    r"(?m)^(?P<num>[0-9０-９]{1,2})\s+(?=\S)",
)

_ARTICLE_HEADING_RE = re.compile(
    r"(?m)^##\s*第\s*([0-9０-９]+)\s*条",
)


def normalize_nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def parse_article_seq_from_heading_line(line: str) -> Optional[int]:
    """Parse Arabic article index from ``## 第4条（…）`` or plain ``第4条`` heading."""
    q = normalize_nfkc(line or "")
    m = _ARTICLE_HEADING_RE.search(q)
    if m:
        raw = "".join(c for c in m.group(1) if c.isdigit())
        return int(raw) if raw else None
    m2 = re.search(r"第\s*([0-9０-９]+)\s*条", q)
    if m2:
        raw = "".join(c for c in m2.group(1) if c.isdigit())
        return int(raw) if raw else None
    return None


def extract_article_seq_from_legacy_article_number(article_number: Any) -> Optional[int]:
    """Best-effort int from legacy ``article_number`` string (PDF loader path)."""
    if article_number is None:
        return None
    s = str(article_number).strip()
    if not s:
        return None
    m = re.search(r"第\s*([0-9０-９]+)\s*条", normalize_nfkc(s))
    if not m:
        return None
    raw = "".join(c for c in m.group(1) if c.isdigit())
    return int(raw) if raw else None


def paragraph_boundaries_in_article_body(body: str) -> List[Tuple[int, int, int]]:
    """Return [(char_start, char_end, paragraph_num), ...] for 項 within article body.

    First block (implicit 第1項) starts after the ``## 第N条`` heading line.
    Subsequent blocks start at lines matching ``^\\s*\\d{1,2}\\s+`` (第2項以降).
    """
    text = body
    if not text.strip():
        return []

    # Skip first line if it is ## 第N条 heading
    lines = text.splitlines(keepends=True)
    start_offset = 0
    if lines:
        first = normalize_nfkc(lines[0])
        if _ARTICLE_HEADING_RE.match(first.strip()):
            start_offset = len(lines[0])
            rest = "".join(lines[1:])
        else:
            rest = text
    else:
        rest = text

    if not rest.strip():
        return [(start_offset, len(text), 1)]

    boundaries: List[Tuple[int, int, int]] = []
    # Character positions in `rest` → add start_offset for absolute positions in `text`
    pos_in_rest = 0
    para_num = 1
    cur_start_rel = 0

    for m in _PARA_START_RE.finditer(rest):
        line_start = m.start()
        if line_start > cur_start_rel:
            abs_start = start_offset + cur_start_rel
            abs_end = start_offset + line_start
            boundaries.append((abs_start, abs_end, para_num))
            para_num += 1
            cur_start_rel = line_start

    abs_start = start_offset + cur_start_rel
    boundaries.append((abs_start, len(text), para_num))

    return boundaries


def chunk_paragraph_assignment(
    chunk_start: int,
    chunk_end: int,
    boundaries: List[Tuple[int, int, int]],
) -> Tuple[Optional[int], str]:
    """Return (paragraph_seq, confidence) for chunk [chunk_start, chunk_end).

    confidence: high | inferred | unknown
    """
    if not boundaries:
        return None, "unknown"

    overlaps: List[Tuple[int, int, int]] = []
    for s, e, p in boundaries:
        lo = max(chunk_start, s)
        hi = min(chunk_end, e)
        if lo < hi:
            overlaps.append((hi - lo, p, s))

    if not overlaps:
        # Chunk outside detected ranges — attach to nearest paragraph by start
        best_p = boundaries[0][2]
        best_d = 10**9
        for s, e, p in boundaries:
            d = min(abs(chunk_start - s), abs(chunk_start - e))
            if d < best_d:
                best_d = d
                best_p = p
        return best_p, "unknown"

    if len(overlaps) == 1:
        return overlaps[0][1], "inferred"

    max_w = max(o[0] for o in overlaps)
    winners = [o for o in overlaps if o[0] == max_w]
    if len(winners) == 1:
        return winners[0][1], "inferred"
    return winners[0][1], "unknown"


def split_preliminary_sections(pre: str) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Split preamble (before first ``## 第N条``) into blocks by single ``# `` headings.

    Returns list of (title_line, block_text, meta) with cite_kind / cite_label.
    """
    pre = (pre or "").strip()
    if not pre:
        return []

    pat = re.compile(r"(?m)^#\s+[^\n]+$")
    matches = list(pat.finditer(pre))
    if not matches:
        return [
            (
                "前文その他",
                pre,
                {
                    "cite_kind": "preamble_other",
                    "cite_label": "前文その他",
                    "article_seq": None,
                },
            )
        ]

    blocks: List[Tuple[str, str, Dict[str, Any]]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(pre)
        block = pre[start:end].strip()
        title_line = m.group(0).strip()
        cite_label, cite_kind = _classify_preamble_heading(title_line)
        blocks.append(
            (
                title_line,
                block,
                {
                    "cite_kind": cite_kind,
                    "cite_label": cite_label,
                    "article_seq": None,
                },
            )
        )
    return blocks


def _classify_preamble_heading(title_line: str) -> Tuple[str, str]:
    t = title_line.strip()
    plain = re.sub(r"^#+\s*", "", t).strip()
    if "別表" in plain:
        return plain[:80], "appendix"
    if "特約" in plain:
        return "特約", "special_terms"
    if "頭書" in plain or "物件" in plain:
        return plain[:80], "head"
    if "設備" in plain or "経過年数" in plain:
        return plain[:80], "appendix"
    return plain[:80] if plain else "前文その他", "preamble_other"


def build_cite_label_article(
    article_seq: int,
    paragraph_seq: Optional[int],
    paragraph_conf: str,
) -> str:
    """Human-readable cite_label cache for article chunks."""
    if paragraph_seq is not None and paragraph_conf in ("high", "inferred"):
        return f"第{article_seq}条第{paragraph_seq}項"
    return f"第{article_seq}条"
