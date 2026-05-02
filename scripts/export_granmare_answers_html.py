#!/usr/bin/env python3
"""Write full-text Q&A HTML tables from granmare CSV exports (scrollable cells).

Run from repo: ``cd rental_rag_poc && python3 scripts/export_granmare_answers_html.py``

Inputs (default): ``tests/outputs/granmare_all_cases_rag_answers.csv``,
``tests/outputs/granmare_important_matters_rag_answers.csv``
"""

from __future__ import annotations

import argparse
import csv
import html
import sys
from pathlib import Path


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:16px;line-height:1.45;max-width:100%;}"
    "h1{font-size:1.35rem;}h2{font-size:1.1rem;margin-top:2rem;scroll-margin-top:8px;}"
    "nav{background:#f5f5f5;padding:12px 16px;border-radius:8px;margin-bottom:1rem;}"
    "nav a{margin-right:1rem;}"
    "table{border-collapse:collapse;width:100%;table-layout:fixed;}"
    "th,td{border:1px solid #ccc;padding:8px;vertical-align:top;}"
    "th{background:#e8e8e8;position:sticky;top:0;z-index:1;}"
    ".id{width:11%;word-break:break-all;}"
    ".label{width:8%;word-break:break-all;}"
    ".q,.a{width:40%;}"
    ".cell-scroll{white-space:pre-wrap;max-height:min(70vh,32rem);overflow-y:auto;word-wrap:break-word;}"
    "small,.src{color:#666;font-size:0.9rem;}"
    "caption{caption-side:top;text-align:left;padding:0.5rem 0;font-weight:600;}"
)


def _table_block(
    rows: list[dict],
    caption: str,
    show_label: bool,
) -> str:
    parts: list[str] = [
        f'<table aria-label="{_esc(caption)}">',
        f"<caption>{_esc(caption)}</caption>",
        "<thead><tr><th class='id'>id</th>",
    ]
    if show_label:
        parts.append("<th class='label'>label</th>")
    parts.append("<th class='q'>質問</th><th class='a'>回答</th></tr></thead><tbody>")
    for r in rows:
        q = r.get("question", "")
        a = r.get("answer_full", r.get("answer_body_400", ""))
        parts.append("<tr>")
        parts.append(f"<td class='id'>{_esc(r.get('id', ''))}</td>")
        if show_label:
            parts.append(
                f"<td class='label'>{_esc(r.get('label', r.get('group', '')))}</td>"
            )
        parts.append(f"<td class='q'><div class='cell-scroll'>{_esc(q)}</div></td>")
        parts.append(f"<td class='a'><div class='cell-scroll'>{_esc(a)}</div></td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def write_html(
    title: str,
    csv_path: Path,
    out_path: Path,
    *,
    show_label: bool = True,
) -> int:
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    parts: list[str] = [
        "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title>",
        f"<style>{_STYLE}</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        f"<p class='src'>ソース: <code>{_esc(str(csv_path))}</code> / {len(rows)} 件</p>",
        _table_block(rows, "質問と回答", show_label=show_label),
        "</body></html>",
    ]
    out_path.write_text("".join(parts), encoding="utf-8")
    return len(rows)


def write_combined_html(
    out_path: Path,
    contract_csv: Path,
    juyo_csv: Path,
) -> None:
    """1ページに契約書ケース + 重要事項ケースの2表を並べる。"""
    c_rows: list[dict] = []
    j_rows: list[dict] = []
    if contract_csv.is_file():
        c_rows = list(csv.DictReader(contract_csv.open(encoding="utf-8")))
    if juyo_csv.is_file():
        j_rows = list(csv.DictReader(juyo_csv.open(encoding="utf-8")))

    title = "グランマーレ Q&A（質問・回答一覧）"
    parts: list[str] = [
        "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title>",
        f"<style>{_STYLE}</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        "<nav><a href='#sec-contract'>契約書ケース</a>",
        "<a href='#sec-juyo'>重要事項ケース</a></nav>",
        f"<p class='src'>契約: <code>{_esc(str(contract_csv))}</code>（{len(c_rows)} 件） / ",
        f"重要事項: <code>{_esc(str(juyo_csv))}</code>（{len(j_rows)} 件）</p>",
        f"<h2 id='sec-contract'>1. 契約書（条文・特約等）ケース</h2>",
        _table_block(c_rows, "契約書ケース", show_label=True) if c_rows else "<p>（CSV なし）</p>",
        f"<h2 id='sec-juyo'>2. 重要事項説明書ケース</h2>",
        _table_block(j_rows, "重要事項ケース", show_label=True) if j_rows else "<p>（CSV なし）</p>",
        "</body></html>",
    ]
    out_path.write_text("".join(parts), encoding="utf-8")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "tests" / "outputs"
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=out_dir,
        help="Output directory for HTML files",
    )
    args = p.parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs = [
        (
            "グランマーレ契約書ケース — 回答全文",
            root / "tests" / "outputs" / "granmare_all_cases_rag_answers.csv",
            out_dir / "granmare_contract_answers_full_table.html",
        ),
        (
            "グランマーレ重要事項ケース — 回答全文",
            root / "tests" / "outputs" / "granmare_important_matters_rag_answers.csv",
            out_dir / "granmare_juyo_answers_full_table.html",
        ),
    ]
    for title, csv_path, html_path in pairs:
        if not csv_path.is_file():
            print(f"Skip (missing): {csv_path}", file=sys.stderr)
            continue
        n = write_html(title, csv_path, html_path, show_label=True)
        print(f"Wrote {html_path} ({n} rows)")

    comb = out_dir / "granmare_qa_tables_combined.html"
    c_csv = root / "tests" / "outputs" / "granmare_all_cases_rag_answers.csv"
    j_csv = root / "tests" / "outputs" / "granmare_important_matters_rag_answers.csv"
    if c_csv.is_file() or j_csv.is_file():
        write_combined_html(comb, c_csv, j_csv)
        print(f"Wrote {comb} (combined)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
