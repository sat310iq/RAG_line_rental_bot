# RENTAL_RAG_POC 実装サマリー（再利用向け）

## 目的
本PoCで実装・検証した設計/実装/運用知見を、他のPoCやプロジェクトで再利用できる形で整理する。上位LLMによるレビューや次期計画の入力として使える内容を意図する。

## 概要
本PoCは「CSV優先のFAQ回答」と「PDF契約書の補完検索」を組み合わせ、**検索順序とスコア閾値で誤回答を抑制**し、**段階的フォールバック（CSV → PDF → 管理会社問い合わせ）**を実現した。  
運用観点では、**キャッシュのKB追従**、**ログの分岐可視化**、**チャネル別出力（LINE/CLI）**を整備した。

## 主要な設計・実装ポイント

### 1. CSV優先＋段階的フォールバック
- **CSVを第一優先**とし、スコア閾値未達時のみPDF検索へフォールバック。
- **PDFも未達なら固定文言**で問い合わせ誘導。
- **CSVキーワード一致があればスコア閾値を無視**してCSV採用（誤回答防止と速度の両立）。
- スコア閾値は **ソース別に管理**（CSV/PDF）。

### 2. 検索スコアの統一返却
- `vector_store_manager.search()` を **`document + score + source + retriever`** の構造で返却。
- スコアは `vector` の距離から正規化し、BM25はキーワード一致で近似。
- スコア統合により「閾値判定」「ロギング」「後続フィルタ」を統一。

### 3. 出力整形の統一（V2 only）
- `render_answer_text()` を **summary優先**に統一。
- `items` は **根拠表示**に回し、本文重複を抑制。
- LINEでは **回答＋緊急・注意のみ**（根拠/Slack連携データは非表示）。

### 4. キャッシュ管理
- **KB更新時刻でキャッシュ無効化**（バージョンキー）。
- `/clear_cache` と `--reset-cache` で運用クリア可能。

### 5. CSV整備と安全運用
- `faq_kb.csv` の列ズレを矯正し、キーワード表現を `|` 区切りに統一。
- `answer_complete` と `fallback_to_master` を運用で制御。
- キーワードの表記ゆれ（犬/猫/イヌ/ネコ等）を吸収。

### 6. 再インデックスの堅牢化
- Chromaの既存コレクションを明示削除して再構築（残骸問題の解消）。

## 運用・UX上の重要な知見
- **誤回答の原因は検索順位のズレと閾値未定義**であることが多い。  
  → スコア閾値＋ログ＋CSV強制採用の3点で改善。
- **緊急時の無回答はUX上の致命傷**。  
  → required_inputsがあっても緊急時は回答本文を出す方針へ修正。
- **チャネル差分は出力制御のみで吸収可能**。  
  → LINEは最小出力、CLIは詳細出力、Slack連携データはチャネルで制御。

## テスト資産
- **CSVキーワードテストレポート**: `docs/CSV_KEYWORD_TEST_REPORT_20260207.md`
- **テスト計画書**: `docs/TEST_PLAN_RAG_20260207.md`
- **テスト戦略ガイド**: `docs/TEST_STRATEGY_GUIDE_20260207.md`
- **pytest雛形**: `tests/test_rag_fallback_plan.py`
- **envテンプレ**: `env.test.example`

## 上位LLMレビュー向けの評価観点（推奨）
1. **検索分岐の透明性**  
   - CSV閾値未達→PDF→fallback のログが明確か
2. **誤回答リスク**  
   - キーワード一致の強制採用が誤爆を起こさないか
3. **運用性**  
   - キャッシュ操作/出力チャネル切替が現場で使えるか
4. **将来拡張性**  
   - ソース追加（OPS/別CSV）時に閾値/ログ設計が拡張可能か

## 次期計画へのインプット
- **スコア正規化の精緻化**: BM25/Vectorの統一指標化と重み調整。
- **キーワードの構造化強化**: CSVをJSON配列化して可読性/メンテ性を向上。
- **LLM出力の決定性**: モック化/再現性強化のテスト基盤整備。
- **チャネルごとのUI定義**: LINE/Slack/CLIの表示仕様を明文化。

---

# RENTAL_RAG_POC Implementation Summary (For Reuse)

## Purpose
Summarize the design, implementation, and operational learnings from this PoC so they can be reused in other PoCs/projects, and serve as input for senior-LLM reviews and future planning.

## Overview
This PoC combines **CSV-first FAQ answers** with **PDF contract fallback**, suppressing wrong answers via **search ordering and score thresholds** and implementing a **tiered fallback (CSV → PDF → contact management)**.  
Operationally, it adds **KB-aware cache invalidation**, **decision-branch logging**, and **channel-specific outputs (LINE/CLI)**.

## Key Design/Implementation Points

### 1) CSV-first + Tiered Fallback
- Always prioritize CSV; fall back to PDF only when below threshold.
- If PDF also fails, return a fixed “contact management” message.
- If any CSV keyword matches, **skip score threshold** and use CSV.
- Thresholds are managed **per source** (CSV/PDF).

### 2) Unified Scored Retrieval
- `vector_store_manager.search()` returns **`document + score + source + retriever`**.
- Vector distances are normalized to scores; BM25 uses keyword match as a proxy.
- Unified scoring enables consistent thresholding, logging, and filtering.

### 3) Output Formatting (V2 Only)
- `render_answer_text()` is **summary-first**.
- `items` are moved to **evidence display** to avoid duplication.
- LINE output shows **answer + urgency label only**; evidence and Slack payloads are hidden.

### 4) Cache Management
- Cache is invalidated by **KB update timestamp** (version key).
- Operators can clear via `/clear_cache` or `--reset-cache`.

### 5) CSV Hygiene & Safety
- Fixed column misalignment and standardized keyword format (`|` separated).
- Operational flags (`answer_complete`, `fallback_to_master`) control behavior.
- Added synonym variants (e.g., 犬/猫/イヌ/ネコ).

### 6) Reindex Robustness
- Explicitly delete existing Chroma collections before reindexing to avoid stale remnants.

## Operational/UX Insights
- Wrong answers often stem from **rank drift + missing thresholds** → solved by thresholds + logs + CSV override.
- **No-answer in urgent cases** is a UX failure → urgent cases must still show answer text.
- Channel differences can be handled by **output-only controls** (LINE minimal vs CLI verbose).

## Test Assets
- CSV Keyword Test Report: `docs/CSV_KEYWORD_TEST_REPORT_20260207.md`
- Test Plan: `docs/TEST_PLAN_RAG_20260207.md`
- Test Strategy Guide: `docs/TEST_STRATEGY_GUIDE_20260207.md`
- Pytest template: `tests/test_rag_fallback_plan.py`
- env template: `env.test.example`

## Suggested Review Dimensions (Senior LLM)
1. **Decision transparency**: clear CSV→PDF→fallback logging
2. **Misanswer risk**: keyword override risk and mitigation
3. **Operability**: cache controls, channel toggles
4. **Extensibility**: adding new sources (OPS/extra CSVs) without redesign

## Inputs for Next Phase
- Better score normalization/weighting between BM25 and vector
- Structured keyword lists (JSON arrays) for maintainability
- Deterministic testing via LLM mocking
- Formal channel-specific UI specs (LINE/Slack/CLI)

