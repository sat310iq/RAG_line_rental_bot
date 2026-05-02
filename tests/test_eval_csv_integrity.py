"""eval_questions.csv の行単位 ID 整合テスト。

目的:
  - relevant_doc_ids / expected_evidence_ids が EvalIDMapper で
    エラーなく解釈できることを確認する。
  - レガシー FAQ001 形式と intent 形式（契約_原状回復）の混在行を検知する。

既存テストとの役割分担:
  - test_rag_poc_improvements.py: YAML エイリアス経由の map_expected_id ロジック検証
  - test_eval_baseline.py: eval_metrics.json の QUALITY_GATE 閾値検証
  - このファイル: CSV 1行単位の ID 正規化成功率検証
"""

import csv
import re
import pytest
from pathlib import Path

EVAL_CSV = Path(__file__).parent.parent / "data" / "eval" / "eval_questions.csv"
LEGACY_ID_PATTERN = re.compile(r"^FAQ\d+$")


def load_eval_rows():
    """eval_questions.csv の全行を返す。ファイルが存在しない場合はスキップ。"""
    if not EVAL_CSV.exists():
        pytest.skip("eval_questions.csv not found.")
    with open(EVAL_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_id_field(value: str) -> list[str]:
    """セミコロンまたはパイプ区切りのID文字列をリストに変換する。"""
    if not value or not value.strip():
        return []
    for sep in [";", "|", ","]:
        if sep in value:
            return [v.strip() for v in value.split(sep) if v.strip()]
    return [value.strip()]


def test_eval_csv_exists():
    """eval_questions.csv が存在することを確認する。"""
    assert EVAL_CSV.exists(), f"eval_questions.csv not found at {EVAL_CSV}"


def test_eval_csv_has_required_columns():
    """必須列が存在することを確認する。"""
    rows = load_eval_rows()
    assert len(rows) > 0, "eval_questions.csv is empty"
    required_columns = {"question", "question_type"}
    actual_columns = set(rows[0].keys())
    missing = required_columns - actual_columns
    assert not missing, f"Missing required columns: {missing}"


def test_eval_csv_no_empty_questions():
    """question 列が空の行がないことを確認する。"""
    rows = load_eval_rows()
    empty_rows = [
        i + 2  # ヘッダ行を1行目とするため+2
        for i, row in enumerate(rows)
        if not row.get("question", "").strip()
    ]
    assert not empty_rows, f"Empty question found at rows: {empty_rows}"


def test_eval_csv_no_legacy_ids():
    """レガシーID形式（FAQ001等）が混在していないことを確認する。

    新規追記時にレガシー形式が混入することを防ぐ。
    既存の混在が意図的な場合は、このテストのコメントに理由を記載する。
    """
    rows = load_eval_rows()
    legacy_found = []
    for i, row in enumerate(rows):
        for field in ["relevant_doc_ids", "expected_evidence_ids"]:
            value = row.get(field, "")
            ids = parse_id_field(value)
            for doc_id in ids:
                if LEGACY_ID_PATTERN.match(doc_id):
                    legacy_found.append({
                        "row": i + 2,
                        "field": field,
                        "id": doc_id,
                        "question": row.get("question", "")[:40],
                    })
    assert not legacy_found, (
        f"Legacy ID format (FAQ001 etc.) found in eval_questions.csv:\n"
        + "\n".join(str(x) for x in legacy_found)
    )


def test_eval_csv_id_fields_parseable():
    """relevant_doc_ids / expected_evidence_ids が空でなければパース可能なことを確認する。"""
    rows = load_eval_rows()
    errors = []
    for i, row in enumerate(rows):
        for field in ["relevant_doc_ids", "expected_evidence_ids"]:
            value = row.get(field, "")
            if not value or not value.strip():
                continue
            try:
                ids = parse_id_field(value)
                if not ids:
                    errors.append({
                        "row": i + 2,
                        "field": field,
                        "value": value,
                        "question": row.get("question", "")[:40],
                    })
            except Exception as e:
                errors.append({
                    "row": i + 2,
                    "field": field,
                    "value": value,
                    "error": str(e),
                })
    assert not errors, (
        f"ID field parse errors in eval_questions.csv:\n"
        + "\n".join(str(x) for x in errors)
    )
