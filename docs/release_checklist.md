# リリースチェックリスト（スケルトン・Phase 2 本格化予定）

Phase 1 では**運用前の人間が見る欄**として枠だけ置く。詳細化・ゲート化は Phase 2 で [eval.md](eval.md) / ADR と整合させる。

## デプロイ前

- [ ] `python3 scripts/preflight_check.py` が成功する（KB ハッシュと manifest 一致）
- [ ] 変更後は `python3 scripts/reindex_vector_db.py` 済み（KB 変更時）
- [ ] Cloud Run のメモリ・タイムアウト・必須環境変数（OpenAI, LINE, 任意 Pub/Sub）を確認
- [ ] 本番 URL で `GET /ready` が 200

## 評価・品質

- [ ] 代表質問（例: [eval/datasets/line_rag_eval_v1.csv](../eval/datasets/line_rag_eval_v1.csv) から抜粋）で `run_eval.py` を実行し、JSONL を保存
- [ ] `summarize_eval.py` でレイテンシ・カテゴリを確認
- [ ] 必要に応じ `review_failures.py` で人間レビュー行を抽出

## ドキュメント

- [ ] 意思決定は `docs/decisions/` の ADR か `logs/decision_events.jsonl` に追記

## 公開前セキュリティガード（必須）

- [ ] ファイルスキャンを実行し、実キー/トークン混入がない
  - `grep -r "OPENAI_API_KEY" .`
  - `grep -r "sk-" .`
  - `grep -r "Bearer " .`
  - `grep -r "AIza" .`
  - `grep -r "ya29\\." .`
- [ ] Git履歴スキャンを実行し、漏えい履歴がない
  - `git log --all -p | grep -E "sk-|OPENAI|Bearer|AIza|ya29\\."`
  - `git log -p | grep -i "api_key"`
  - `git log -p | grep -i "sk-"`
- [ ] 実値 `.env` は非公開、テンプレートのみ公開されている
  - 公開可: `env.example`, `env.gcp.example`, `deploy/.env.gcp.example`
  - 非公開: `.env`, `.env.gcp`, `deploy/.env.gcp`
- [ ] 漏えい検知時の対応を実施済み
  - 履歴洗浄: `git filter-repo` または BFG Repo-Cleaner
  - 露出疑いキーの無効化・再発行（ローテーション）

## 明示的に Phase 2 で厚くする予定

- スモークの自動合否、レシピの手順完全版、Ragas / 本格回帰のゲート
