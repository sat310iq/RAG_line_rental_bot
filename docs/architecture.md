# アーキテクチャ（LINE RAG PoC）

## 高レベルフロー

1. LINE Webhook 受信（`src/interfaces/line/`、`src/api/main.py` 経由の Uvicorn）
2. 署名検証・（設定に応じた）冪等性
3. 質問を `RAGAnswerer` へ渡す
4. **階層検索**: Deal（CSV/KB）→ 必要に応じ Master（PDF）
5. `Responder` または構造化 LLM 経路で `AnswerSchema`（V2）を生成
6. `render_answer_text` でユーザー向け文字列化し LINE 返信
7. 運用・評価用メトリクス（既存の `run_simple_eval.py` / Opik 等）は別系統

## 起動エントリと KB 優先経路

- 本番コンテナの起動エントリは `uvicorn src.api.main:app`（`Dockerfile` の `CMD`）
- `src/api/main.py` は `src/interfaces/line/main.py` の `app` を再エクスポートする薄い入口
- Deal 側の主データソースは `data/faq_kb.csv`（`kb_csv_path`）で、運用時はこの KB を優先する

## 主要コンポーネント

| コンポーネント | 役割 |
|----------------|------|
| Webhook / Handler | LINE イベントの受信と応答 |
| `VectorStoreManager` | Chroma + BM25 等の検索基盤 |
| `QueryCache` | 同一質問のキャッシュ |
| `RAGAnswerer` | ルーティング、検索、回答生成のオーケストレーション |
| `Responder` | KB FAQ 主体の回答生成（スキーマ列制御） |
| `TenantAuth` | 本人向け情報の制限（任意） |

## 設計原則

- ホットパスを短く保つ（重い初期化は起動時・遅延 import に寄せる）
- CSV / PDF の優先順位を明示
- 検索失敗と生成失敗をログで区別しやすくする
- Cloud Run 上では CPU スロットリング・タイムアウト・メモリを考慮（詳細は [docs/deploy/](deploy/)）

## リスクと緩和

| リスク | 緩和の例 |
|--------|-----------|
| タイムアウト前に返信できない | 非同期処理・設定見直し（運用ドキュメント参照） |
| Webhook 重複 | 冪等キー・重複排除 |
| メモリ（埋め込みモデル等） | キャッシュ・遅延ロード・インスタンスサイズ |
| CSV / PDF の矛盾 | 適用順ポリシーとエスカレーション |
| 幻覚 | 根拠拘束プロンプト・エスカレーション |

## 評価の二系統

- **本番相当の詳細評価**: `scripts/run_simple_eval.py` + `src/evaluate.py`（変更しない）
- **軽量・人間レビュー向け**: `scripts/run_eval.py` → `eval/runs/*.jsonl`（本ドキュメントの Amplifier 運用）
- **運用・ダッシュボード・既存 Opik レポート**: [docs/eval/](eval/) 配下（`OPIK_*` 等）。**プロダクト仕様の芯**は上記 3 ファイル（`spec` / `architecture` / ルート隣接の [eval.md](eval.md)）に置く方針（役割の重複を避けたい場合は [eval.md](eval.md) の「既存評価との役割分担」を正とする）。

## 実験ブランチとワークツリー（推奨）

- 大きなルーティング・CSV 優先度の実験は、ローカルで `exp/<topic>` や `exp/csv-first` など**短命ブランチ**に切ると、本番用 `main` との差分が追いやすい。
- **Git worktree**で並行作業する場合は、同一リポジトリに複数チェックアウトを置き、`data/vector_store` や `.env` を衝突させないこと（本リポジトリが非 git 環境の場合は手元の作業用ディレクトリ分離で同様の効果を狙う）。

## Phase 2（本リポジトリ内の扱い）

- `docs/release_checklist.md` の本格運用、固定レシピ群（`docs/recipes/*`）、Failure taxonomy の運用固定は **Phase 1 完了後**の別作業とする。薄い [release_checklist](release_checklist.md) スケルトンは入門用のチェック欄として共存する。
