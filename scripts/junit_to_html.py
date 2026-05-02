#!/usr/bin/env python3
"""Convert pytest JUnit XML to a simple HTML report.

Usage:
  python3 -m pytest --junitxml=tests/outputs/pytest_results.xml -q
  python3 scripts/junit_to_html.py
"""

from __future__ import annotations

import html
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    xml_path = root / "tests" / "outputs" / "pytest_results.xml"
    out_path = root / "tests" / "outputs" / "pytest_report.html"
    if not xml_path.is_file():
        print(f"Missing: {xml_path}\nRun: pytest --junitxml={xml_path}", file=sys.stderr)
        return 1

    tree = ET.parse(xml_path)
    el = tree.getroot()
    # single testsuite
    ts = el.find("testsuite") if el.tag != "testsuite" else el
    if ts is None:
        ts = el

    total = int(ts.get("tests", 0))
    failures = int(ts.get("failures", 0))
    errors = int(ts.get("errors", 0))
    skipped = int(ts.get("skipped", 0))
    passed = total - failures - errors - skipped
    t_sec = float(ts.get("time", 0) or 0)
    hostname = ts.get("hostname", "")
    timestamp = ts.get("timestamp", "")

    rows: list[str] = []
    for tc in ts.findall("testcase"):
        cls = html.escape(tc.get("classname", ""))
        name = html.escape(tc.get("name", ""))
        t = tc.get("time", "")
        sk = tc.find("skipped")
        if sk is not None:
            msg = html.escape((sk.get("message") or "")[:240])
            status = f'<span class="skip">skipped</span><br><small class="msg">{msg}</small>'
        elif tc.find("failure") is not None:
            status = '<span class="fail">failed</span>'
        elif tc.find("error") is not None:
            status = '<span class="err">error</span>'
        else:
            status = '<span class="ok">passed</span>'
        rows.append(
            f"<tr><td>{cls}</td><td>{name}</td><td>{t}</td><td>{status}</td></tr>"
        )

    body = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pytest レポート</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 1.5rem; background: #fafafa; color: #222; }}
  h1 {{ font-size: 1.25rem; }}
  .summary {{ display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0; }}
  .card {{ background: #fff; border: 1px solid #ddd; border-radius: 8px; padding: 0.75rem 1.25rem; min-width: 6rem; }}
  .card strong {{ display: block; font-size: 1.5rem; }}
  .ok {{ color: #0a0; }} .skip {{ color: #a60; }} .fail {{ color: #c00; }} .err {{ color: #c00; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 0.85rem; }}
  th, td {{ border: 1px solid #ddd; padding: 0.35rem 0.5rem; text-align: left; }}
  th {{ background: #eee; position: sticky; top: 0; }}
  tr:nth-child(even) {{ background: #f9f9f9; }}
  .msg {{ font-size: 0.8rem; color: #555; max-width: 32rem; }}
  .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 0.5rem; }}
  .wrap {{ max-height: 70vh; overflow: auto; border: 1px solid #ddd; border-radius: 6px; }}
</style>
</head>
<body>
  <h1>pytest テスト結果</h1>
  <p class="meta">生成: {html.escape(datetime.now().isoformat(timespec="seconds"))}
  {f" / XML: {html.escape(timestamp)}" if timestamp else ""}
  {f" / {html.escape(hostname)}" if hostname else ""}</p>
  <div class="summary">
    <div class="card"><span>合計</span><strong>{total}</strong></div>
    <div class="card"><span class="ok">成功</span><strong class="ok">{passed}</strong></div>
    <div class="card"><span class="skip">スキップ</span><strong class="skip">{skipped}</strong></div>
    <div class="card"><span class="fail">失敗</span><strong class="fail">{failures}</strong></div>
    <div class="card"><span class="err">エラー</span><strong class="err">{errors}</strong></div>
    <div class="card"><span>所要(秒)</span><strong>{t_sec:.2f}</strong></div>
  </div>
  <p>ソース: <code>tests/outputs/pytest_results.xml</code>（<code>pytest --junitxml=...</code> で更新）</p>
  <div class="wrap">
  <table>
    <thead>
      <tr><th>クラス</th><th>テスト名</th><th>秒</th><th>結果</th></tr>
    </thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
  </div>
</body>
</html>"""

    out_path.write_text(body, encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
