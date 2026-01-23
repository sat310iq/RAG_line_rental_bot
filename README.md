# 賃貸入居者向け 3ソース統合RAG PoC

macOS上でローカル実行できる賃貸入居者向けQAチャットボットのPoC実装です。
PDF、FAQ CSV、運用ログCSVの3ソースを統合したRAGシステムで、2025標準ガイドライン（Hybrid+RRF+Semantic Rerank、Plan/Retrieve/Fuse分離、構造化出力）に準拠しています。

## 機能

- **3ソース統合RAG**: PDF（契約/ガイドライン）、FAQ CSV、運用ログCSVから情報を検索
- **Hybrid Retrieval**: BM25（キーワード）+ Vector（意味類似）の統合検索
- **RRF Fusion**: 複数検索結果の統合
- **Semantic Reranking**: LLMベースの再ランキング
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
- `data/dispute_guideline_faq.csv` を作成（FAQ CSV）
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
# 評価データセットで実行
python scripts/run_eval.py

# 結果分析
python scripts/analyze_eval.py
```

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
│   ├── csv_qa_loader.py        # CSVローダ（FAQ/運用ログ）
│   ├── vector_store_manager.py # ベクトルストア管理
│   ├── query_cache.py          # クエリキャッシュ
│   ├── rag_answerer.py         # RAG回答生成
│   └── rental_qa_chat.py       # CLIインターフェース
├── scripts/
│   ├── reindex_vector_db.py    # 再インデックス
│   ├── smoke_test.py           # スモークテスト
│   ├── run_eval.py             # 評価実行
│   └── analyze_eval.py          # 評価分析
├── tests/
│   ├── test_csv_loader.py
│   ├── test_masking.py
│   ├── test_retrieval_smoke.py
│   ├── test_answer_policy.py
│   └── test_eval_baseline.py
└── data/
    ├── documents/              # PDFファイル
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
