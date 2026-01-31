# 賃貸入居者向け 3ソース統合RAG PoC

macOS上でローカル実行できる賃貸入居者向けQAチャットボットのPoC実装です。
PDF、KB CSV（15列スキーマ）、運用ログCSVの3ソースを統合したRAGシステムで、2025標準ガイドライン（Hybrid+RRF+Semantic Rerank、Plan/Retrieve/Fuse分離、構造化出力）に準拠しています。

## ナレッジベースCSV（15列スキーマ）

本システムは、**15列スキーマのナレッジベースCSV**（`data/faq_kb.csv`）を推奨データソースとして使用します。各列は回答生成を制御するパラメータとして機能し、LLMの暴走・誤回答を抑えます。

### CSV列定義

| 列名 | 型 | 説明 |
|------|-----|------|
| intent | string | FAQ項目の一意識別子（例: "設備_水漏れ"） |
| category | string | 大分類（例: ゴミ/設備/契約/防犯/生活/規則/共用部） |
| keywords | string | 検索用キーワード（スペース区切り） |
| answer | string | 基本回答（RAGは原則この答えをベースに返す） |
| response_type | enum | fact/instruction/warning/policy（返答トーン制御） |
| confidence_level | enum | high/medium/low（断定度制御） |
| required_inputs | string | 追加ヒアリング項目（カンマ区切り） |
| urgency | enum | low/medium/high（SLA・冒頭文制御） |
| conditions | string | 適用条件 |
| effective_from | date | 有効開始日（YYYY-MM-DD、空欄可） |
| effective_to | date | 有効終了日（YYYY-MM-DD、空欄可） |
| escalation | enum | bot_only/management_required/owner_required/conditional_owner |
| escalation_reason | string | エスカレーション理由 |
| handoff_message | string | Slack/チケット用の引継ぎ文 |
| notes | string | 運用メモ（返答には出さない） |

### CSV追加方法

1. `data/faq_kb.csv` を編集
2. 15列すべてを埋める（空欄可の列は空欄でも可）
3. `python scripts/reindex_vector_db.py` を実行して再インデックス

詳細は `data/faq_kb.csv` のサンプルデータを参照してください。

## 機能

- **3ソース統合RAG**: PDF（契約/ガイドライン）、KB CSV（15列スキーマ）、運用ログCSVから情報を検索
- **スキーマ列ベース制御**: CSVの各列を制御パラメータとして使用し、LLMの暴走・誤回答を抑制
- **Hybrid Retrieval**: BM25（キーワード）+ Vector（意味類似）の統合検索
- **RRF Fusion**: 複数検索結果の統合
- **Semantic Reranking**: LLMベースの再ランキング
- **日付有効性判定**: effective_from/toに基づく自動フィルタリング
- **本人確認**: 簡易認証により、本人の号室＋氏名のみを回答に含める
- **情報漏えい対策**: PII検知・マスキング、本人フィルタリング
- **構造化出力**: 結論/根拠/次アクション/注意点の固定フォーマット

## セットアップ

### 前提条件

- Python 3.11+
- macOS（ローカルCLI実行）

### インストール手順

1. 仮想環境を作成・有効化:
```bash
cd rental_rag_poc
python3.11 -m venv .venv
source .venv/bin/activate
```

2. 依存関係をインストール:
```bash
pip install -r requirements.txt
```

3. 環境変数を設定:
```bash
cp .env.example .env
# .env を編集して OPENAI_API_KEY を設定
```

4. データファイルを配置:
- `data/documents/` にPDFファイルを配置
- `data/faq_kb.csv` を作成（15列スキーマのナレッジベースCSV）※推奨
- `data/dispute_guideline_faq.csv` を作成（FAQ CSV、後方互換性のため）
- `data/faq_data.csv` を作成（運用ログCSV）
- `data/tenants.csv` を作成（入居者マスタ: contract_id,room_number,name,pin,phone,email）

## 使用方法

### 初回セットアップ（データインデックス作成）

```bash
python scripts/reindex_vector_db.py
```

### CLIチャット起動

```bash
python -m src.rental_qa_chat
```

起動時に契約IDとPINの入力が求められます。認証成功後、質問を入力して回答を得られます。

### 評価実行

```bash
# 評価データセットで実行（5件のテストモード）
python scripts/run_simple_eval.py

# 結果分析
python scripts/analyze_eval_results.py
```

評価結果は以下の場所に保存されます：
- `data/eval/eval_results.jsonl`: 個別の評価結果（JSON Lines形式）
- `data/eval/eval_metrics.json`: 集計メトリクス
- `data/eval/eval_analysis.json`: 詳細分析結果（`analyze_eval_results.py`実行後）

評価メトリクスはComet ML (OPIK)にも記録されます。`ENABLE_COMET_LOGGING=true`を設定している場合、`RAG_POC`プロジェクトのExperimentsタブで確認できます。

#### 評価メトリクスの見方

評価スクリプトは以下のメトリクスを計算します：

- **Recall@5 / Recall@10**: 期待されるドキュメントが検索結果の上位5件/10件に含まれる割合（0-1、高いほど良い）
- **MRR (Mean Reciprocal Rank)**: 期待されるドキュメントが最初に出現する順位の逆数の平均（0-1、高いほど良い）
- **Relevance**: 回答が質問に関連しているか（0-1、高いほど良い）
- **Hallucination**: 回答に根拠情報に基づかない情報が含まれる割合（0-1、低いほど良い）
- **PII Leakage Rate**: 個人情報が漏洩した質問の割合（0-1、低いほど良い）
- **Prohibited Mention Rate**: 禁止事項が言及された質問の割合（0-1、低いほど良い）

**目標値**:
- Recall@5: 0.50以上（現在: 0.25）
- Hallucination: 0.50以下（現在: 0.53）
- PII Leakage Rate: 0.00（現在: 0.00）✅
- Prohibited Mention Rate: 0.10以下（現在: 0.10）✅

評価結果の詳細は`data/eval/eval_analysis.json`を確認してください。検索失敗やハルシネーションのパターンが分析されています。

### スモークテスト

```bash
python scripts/smoke_test.py
```

## プロジェクト構造

```
rental_rag_poc/
├── src/
│   ├── config.py              # 設定管理
│   ├── tenant_auth.py          # 本人確認
│   ├── document_loader.py      # PDFローダ
│   ├── csv_qa_loader.py        # CSVローダ（FAQ/運用ログ、後方互換）
│   ├── kb_loader.py            # KB CSVローダ（15列スキーマ）※新規
│   ├── responder.py            # レスポンス生成（スキーマ列ベース制御）※新規
│   ├── vector_store_manager.py # ベクトルストア管理（有効性判定含む）
│   ├── query_cache.py          # クエリキャッシュ
│   ├── rag_answerer.py         # RAG回答生成（Responder統合）
│   ├── eval_id_mapper.py       # 評価用IDマッピング
│   ├── evaluate.py             # 評価ロジック
│   ├── metrics.py              # 評価メトリクス計算
│   ├── opik_integration.py     # OPIK/Comet ML統合
│   └── rental_qa_chat.py       # CLIインターフェース
├── scripts/
│   ├── reindex_vector_db.py    # 再インデックス（KB CSV対応）
│   ├── smoke_test.py           # スモークテスト
│   ├── run_simple_eval.py      # 評価実行（シンプル版）
│   └── analyze_eval_results.py # 評価結果分析
├── tests/
│   ├── test_csv_loader.py
│   ├── test_masking.py
│   ├── test_retrieval_smoke.py
│   ├── test_answer_policy.py
│   └── test_eval_baseline.py
└── data/
    ├── documents/              # PDFファイル
    ├── faq_kb.csv             # ナレッジベースCSV（15列スキーマ）※新規
    ├── eval/                   # 評価データセット
    └── vector_store/           # ChromaDB永続化データ
```

## 開発・テスト

```bash
# ユニットテスト実行
pytest tests/

# 特定のテスト実行
pytest tests/test_masking.py -v
```

## ライセンス

PoC実装のため、ライセンスは未定です。
