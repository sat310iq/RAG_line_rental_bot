# RAGシステム改善ロードマップ（OPIK評価結果ベース）

**最終更新**: 2026-01-31  
**現在の評価メトリクス**: Recall@5=0.25, Hallucination=0.53, 検索失敗率=70%

## 📊 現状分析

### 評価結果サマリー
- **Recall@5**: 0.25（目標: 0.50+）
- **Hallucination**: 0.53（目標: 0.50以下）
- **検索失敗率**: 70%（5件の質問で検索結果が空）
- **PII Leakage Rate**: 0.00 ✅
- **Prohibited Mention Rate**: 0.10 ✅

### 主な問題
1. **検索結果が空**: 5件の質問で検索結果が空（no_retrieved）
   - FAQ: "退去時の原状回復", "契約期間の延長", "管理費の支払い"
   - PDF: "契約で禁止されている行為"
   - Multi: "退去時の立会い検査"
2. **IDマッピング**: 期待されるIDと実際のIDが不一致の可能性
3. **ハルシネーション**: 検索精度の低さと相関

---

## 🔄 OPIK評価結果ベースのチューニングアプローチ

### 基本ワークフロー

各改善ステップで以下のサイクルを繰り返します：

1. **ベースライン評価の実行**
   ```bash
   python scripts/run_simple_eval.py
   ```

2. **OPIKで結果を確認**
   - Comet ML UI: `https://www.comet.com/{workspace}/{project_name}`
   - Experimentsタブで最新の評価結果を確認
   - メトリクスの推移をグラフで確認
   - 個別の質問結果を詳細に分析

3. **問題の特定**
   - 検索失敗した質問を特定
   - ハルシネーションが発生した質問を特定
   - メトリクスの変化を分析

4. **改善の実装**
   - 仮説に基づいて改善を実装
   - 変更内容を明確に記録

5. **再評価と比較**
   - 改善後の評価を実行
   - OPIKで前回の結果と比較
   - 改善効果を定量化

6. **次のステップの決定**
   - 効果が大きい改善を継続
   - 効果が小さい改善は別のアプローチを検討

---

## 🗺️ 段階的改善計画（OPIK評価結果ベース）

### Phase 1: 検索基盤の改善（優先度: 最高）

**目標**: 検索失敗率を70% → 30%以下に削減、Recall@5を0.25 → 0.40以上に改善

#### Step 1.0: ベースライン評価の実行とOPIKでの確認
- **期間**: 15分
- **作業内容**:
  1. 現在の状態で評価を実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Comet ML UIでExperimentsタブを開く
     - 最新の評価結果（experiment名: `eval_YYYYMMDD_HHMMSS`）を確認
     - メトリクス（Recall@5, Hallucination等）を記録
     - 検索失敗した質問を特定（`data/eval/eval_analysis.json`も参照）
  3. ベースラインを記録:
     - `docs/tuning/baseline_metrics.json`に現在のメトリクスを保存
     - 検索失敗パターンを分析
- **成果物**: 
  - ベースラインメトリクスの記録
  - 検索失敗パターンの分析結果
- **OPIKでの確認ポイント**:
  - Recall@5, Recall@10, MRRの値
  - 検索失敗率（no_retrievedの質問数）
  - 個別質問の検索結果（retrieved_ids vs expected_ids）

#### Step 1.1: IDマッピングの検証と改善（rental_rag_poc-340, H3）
- **期間**: 1-2時間
- **作業内容**:
  1. OPIKで検索失敗した質問を確認
  2. `eval_id_mapper.py`のマッピングロジックを確認
  3. 評価データセット（`data/eval/eval_questions.csv`）のID形式を確認
  4. 実際のドキュメントIDと期待されるIDの不一致を特定
  5. マッピングロジックを修正
- **成果物**: 
  - `docs/decision/ADR-0001.md`（IDマッピング改善の記録）
  - 修正された`src/eval_id_mapper.py`
- **検証**: 
  1. 評価スクリプトを実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Recall@5が改善したか確認（目標: +0.10以上）
     - 検索失敗率が改善したか確認
     - 個別質問の検索結果を比較
  3. 改善効果を記録: `docs/tuning/step1.1_results.json`

#### Step 1.2: 検索クエリ生成の改善（rental_rag_poc-340, H1）
- **期間**: 2-3時間
- **作業内容**:
  1. OPIKで検索失敗した質問を再確認
  2. 現在のサブクエリ生成ロジックを分析
  3. 検索失敗した質問のサブクエリをログ出力
  4. サブクエリ生成プロンプトを改善
  5. キーワード抽出の精度向上
- **成果物**:
  - 改善された`src/rag_answerer.py`（`_plan_subqueries`メソッド）
  - 検索ログの分析結果
- **検証**: 
  1. 評価スクリプトを実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Recall@5が改善したか確認（目標: +0.10以上）
     - 検索失敗率が改善したか確認
     - 個別質問の検索結果を比較
  3. 改善効果を記録: `docs/tuning/step1.2_results.json`

#### Step 1.3: ベクトルストアの再インデックス（rental_rag_poc-340, H2）
- **期間**: 30分-1時間
- **作業内容**:
  1. OPIKで現在の検索結果を確認
  2. 現在のベクトルストアの状態を確認
  3. `scripts/reindex_vector_db.py`を実行
  4. インデックスの完全性を確認
- **成果物**:
  - 再インデックスされたベクトルストア
- **検証**: 
  1. 評価スクリプトを実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Recall@5が改善したか確認（目標: +0.05以上）
     - 検索失敗率が改善したか確認
     - 個別質問の検索結果を比較
  3. 改善効果を記録: `docs/tuning/step1.3_results.json`

#### Step 1.4: ハイブリッド検索の重み調整（rental_rag_poc-340, H4）
- **期間**: 1-2時間
- **作業内容**:
  1. OPIKで現在の検索結果を確認
  2. RRF融合の重みを調整（BM25 vs Vector）
  3. 異なる重み設定で評価を実行（複数回）
  4. OPIKで各設定の結果を比較
  5. 最適な重みを決定
- **成果物**:
  - 最適化された重み設定
  - `src/vector_store_manager.py`の更新
  - 各重み設定の評価結果比較
- **検証**: 
  1. 複数の重み設定で評価を実行: `python scripts/run_simple_eval.py`
  2. OPIKで各設定の結果を比較:
     - 各experimentのRecall@5を比較
     - 最適な重み設定を選択
  3. 改善効果を記録: `docs/tuning/step1.4_results.json`

**Phase 1完了条件**: Recall@5 ≥ 0.40、検索失敗率 ≤ 30%

**Phase 1完了時の確認**:
1. OPIKで最終的なメトリクスを確認
2. ベースラインとの比較を記録
3. 改善効果を定量化

---

### Phase 2: ハルシネーション率の改善（優先度: 高）

**目標**: ハルシネーション率を0.53 → 0.50以下に削減

#### Step 2.0: Phase 1完了後の評価とOPIKでの確認
- **期間**: 15分
- **作業内容**:
  1. Phase 1完了後の評価を実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Hallucinationメトリクスを確認
     - ハルシネーションが発生した質問を特定
     - 検索精度との相関を分析
  3. ベースラインを記録: `docs/tuning/phase2_baseline.json`

#### Step 2.1: プロンプトの強化（rental_rag_poc-c9c, H1）
- **期間**: 1-2時間
- **作業内容**:
  1. OPIKでハルシネーションが発生した質問を確認
  2. 現在のプロンプトを確認
  3. 「根拠情報に記載されていない情報は一切含めない」を強化
  4. ハルシネーション例を分析し、プロンプトを改善
- **成果物**:
  - 改善された`src/responder.py`（`generate_llm`メソッド）
  - `docs/decision/ADR-0002.md`
- **検証**: 
  1. 評価スクリプトを実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Hallucinationメトリクスが改善したか確認（目標: 0.50以下）
     - 個別質問のハルシネーションスコアを比較
  3. 改善効果を記録: `docs/tuning/step2.1_results.json`

#### Step 2.2: フォールバック処理の改善（rental_rag_poc-c9c, H3）
- **期間**: 1時間
- **作業内容**:
  1. OPIKで検索結果が空の質問を確認
  2. 検索結果が空の場合の処理を確認
  3. 「情報不足」を明示するフォールバック処理を実装
- **成果物**:
  - 改善された`src/rag_answerer.py`（`answer`メソッド）
- **検証**: 
  1. 評価スクリプトを実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Hallucinationメトリクスが改善したか確認
     - 検索結果が空の質問の回答を確認
  3. 改善効果を記録: `docs/tuning/step2.2_results.json`

**Phase 2完了条件**: ハルシネーション率 ≤ 0.50

**注意**: Phase 2はPhase 1と並行して進めることができますが、検索精度が低いまま（Recall@5 < 0.30）では効果が限定的です。OPIKで検索精度とハルシネーション率の相関を確認しながら進めます。

---

### Phase 3: 高度な機能の実装（優先度: 中）

#### Step 3.1: LLMベースのreranking実装（rental_rag_poc-7e8）
- **期間**: 3-4時間
- **作業内容**:
  1. OPIKで現在の検索結果を確認
  2. `rag_answerer.py`の248行目のTODOを確認
  3. LLMベースのスコアリングを実装
  4. 既存のrerankingと統合
  5. APIコストとレイテンシーを測定
- **成果物**:
  - 実装された`src/rag_answerer.py`（`_semantic_rerank`メソッド）
  - `docs/decision/ADR-0003.md`
- **検証**: 
  1. 評価スクリプトを実行: `python scripts/run_simple_eval.py`
  2. OPIKで結果を確認:
     - Recall@5が改善したか確認（目標: +0.05以上）
     - レイテンシーが許容範囲内か確認
     - APIコストを確認
  3. 改善効果を記録: `docs/tuning/step3.1_results.json`

**注意**: LLM APIコストが高すぎる場合（1回のrerankingで$0.10以上）は、Cross-encoder方式にフォールバック。OPIKでコストと効果のバランスを確認します。

---

### Phase 4: テストカバレッジの向上（優先度: 中）

#### Step 4.1: 新規モジュールのユニットテスト追加（rental_rag_poc-cd0）
- **期間**: 2-3時間
- **作業内容**:
  1. `eval_id_mapper.py`のユニットテスト作成
  2. `kb_loader.py`のユニットテスト作成
  3. `responder.py`のユニットテスト作成（LLM呼び出しをモック）
- **成果物**:
  - `tests/test_eval_id_mapper.py`
  - `tests/test_kb_loader.py`
  - `tests/test_responder.py`
- **検証**: テストカバレッジが80%以上になることを確認

---

## 📅 推奨スケジュール（OPIK評価結果ベース）

### Week 1: Phase 1（検索基盤の改善）
- **Day 1 午前**: Step 1.0（ベースライン評価とOPIK確認）
- **Day 1 午後**: Step 1.1（IDマッピングの検証と改善）
  - 改善後、評価実行 → OPIKで確認 → 効果測定
- **Day 2-3**: Step 1.2（検索クエリ生成の改善）
  - 改善後、評価実行 → OPIKで確認 → 効果測定
- **Day 4**: Step 1.3（ベクトルストアの再インデックス）
  - 改善後、評価実行 → OPIKで確認 → 効果測定
- **Day 5-6**: Step 1.4（ハイブリッド検索の重み調整）
  - 複数設定で評価実行 → OPIKで比較 → 最適設定を選択

### Week 2: Phase 2（ハルシネーション率の改善）
- **Day 1 午前**: Step 2.0（Phase 1完了後の評価とOPIK確認）
- **Day 1 午後-2**: Step 2.1（プロンプトの強化）
  - 改善後、評価実行 → OPIKで確認 → 効果測定
- **Day 3**: Step 2.2（フォールバック処理の改善）
  - 改善後、評価実行 → OPIKで確認 → 効果測定

### Week 3: Phase 3 & 4（高度な機能とテスト）
- **Day 1-3**: Step 3.1（LLMベースのreranking実装）
  - 実装後、評価実行 → OPIKで確認 → コストと効果を評価
- **Day 4-5**: Step 4.1（新規モジュールのユニットテスト追加）

---

## 🎯 マイルストーン

### Milestone 1: 検索基盤の改善完了
- **目標**: Recall@5 ≥ 0.40、検索失敗率 ≤ 30%
- **期限**: Week 1終了時
- **成果物**: ADR-0001.md、改善された検索ロジック

### Milestone 2: ハルシネーション率の改善完了
- **目標**: ハルシネーション率 ≤ 0.50
- **期限**: Week 2終了時
- **成果物**: ADR-0002.md、改善されたプロンプト

### Milestone 3: 高度な機能の実装完了
- **目標**: LLMベースのreranking実装、テストカバレッジ80%以上
- **期限**: Week 3終了時
- **成果物**: ADR-0003.md、ユニットテスト追加

---

## ⚠️ リスクと対策

### リスク1: 検索精度が期待通りに改善しない
- **対策**: 各ステップで評価を実行し、効果を測定。効果が低い場合は次のステップに進む前に原因を分析

### リスク2: LLM APIコストが高すぎる
- **対策**: コストを測定し、$0.10以上の場合、Cross-encoder方式にフォールバック

### リスク3: パフォーマンスの低下
- **対策**: 各改善でレイテンシーを測定し、許容範囲内か確認

---

## 📝 進捗追跡（OPIK評価結果ベース）

各ステップの完了時に以下を更新:
- [ ] 評価スクリプトを実行: `python scripts/run_simple_eval.py`
- [ ] OPIKで結果を確認（Comet ML UI）
- [ ] メトリクスの変化を記録: `docs/tuning/stepX.X_results.json`
- [ ] ADRの作成・更新
- [ ] Beads Issueのステータス更新
- [ ] このロードマップの更新

### OPIKでの確認方法

1. **Comet ML UIにアクセス**
   - URL: `https://www.comet.com/{workspace}/{project_name}`
   - プロジェクト名: `RAG_POC`（環境変数`COMET_PROJECT_NAME`で設定）

2. **Experimentsタブで評価結果を確認**
   - 最新のexperiment（`eval_YYYYMMDD_HHMMSS`）を選択
   - メトリクスタブで以下のメトリクスを確認:
     - `avg_recall_at_5`, `avg_recall_at_10`, `avg_mrr`
     - `avg_relevance`, `avg_hallucination`
     - `pii_leakage_rate`, `prohibited_mention_rate`

3. **個別質問の結果を確認**
   - 各質問の`retrieved_ids`と`expected_ids`を比較
   - 検索失敗（`no_retrieved`）の質問を特定
   - ハルシネーションが発生した質問を特定

4. **メトリクスの推移を確認**
   - 複数のexperimentを比較して改善効果を確認
   - グラフでメトリクスの推移を可視化

### 評価結果の記録

各ステップで以下の情報を記録:
- 改善前のメトリクス（ベースライン）
- 改善後のメトリクス
- 改善効果（差分）
- 検索失敗した質問の変化
- ハルシネーションが発生した質問の変化

---

## 🔗 関連Issue

- rental_rag_poc-340: 検索精度の改善（Recall@5: 0.25 → 0.50+）
- rental_rag_poc-c9c: ハルシネーション率の改善（0.53 → 0.50以下）
- rental_rag_poc-7e8: LLMベースのreranking実装
- rental_rag_poc-cd0: 新規モジュールのユニットテスト追加
