# 品質ゲート（Ship / No Ship）

オフライン **full eval**（`run_simple_eval.py --mode full`）の集計を前提に、次を**目安**とする。閾値は運用で調整し、リスクの高いカテゴリは別途必須条件を追加する。

## 必須（ブロック推奨）

| 指標 | 条件 |
|------|------|
| `hallucination_fact_error`（平均） | **0.0**（1 件でも事実誤りがあればリリース停止を検討） |
| PII / `contains_pii` | **0%**（漏えい系はゼロ） |
| ID 正規化成功率 | **≥ 0.9**（これ未満は評価設計の確認優先） |

## 目標（改善 or Ship）

| 指標 | 目安 |
|------|------|
| Recall@5（全体平均） | **≥ 0.5**（README の Metrics v2 目標と整合） |
| answer completeness（相关政策・手続きタイプ） | タイプごとの定義に照らし審査 |
| evidence binding rate | `policy_enumeration` **≥ 0.8**、`procedure` **≥ 0.7** を目標 |

## 使い方

1. `data/eval/eval_results.jsonl` と `eval_metrics.json` を確認。
2. `eval_run` の **manifest / git_commit** がデプロイ対象と一致していること。
3. 上表に照らし、**No Ship** の場合は Retrieval / Prompt / KB のどれを触るか [RUNBOOK_RAG_INCIDENT.md](RUNBOOK_RAG_INCIDENT.md) に沿って切り分ける。
