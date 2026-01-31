# Beadsタスク作成テンプレート

## 使用方法

今後Beadsを使う時は、以下のフォーマットでタスクを作成してください。

---

# 🎯 Objective
- このタスクの目的を1文で書く（何が出来れば勝ちか）

# ✅ Success Criteria（合否）
- Must（必須）:
  1)
  2)
- Should（望ましい）:
  1)
- Kill Criteria（中止条件）:
  - 例：XXが解決できない場合は方針転換/撤退

# 🧭 Decision Hygiene Protocol（このタスクの"衛生手順"）
## 0. Sequencing（順序固定）
- (1) 現状観測 → (2) 仮説列挙 → (3) 反証テスト設計 → (4) 実装 → (5) テスト → (6) 決定ログ更新
- 途中で結論に飛ばない（修正衝動を抑える）

## 1. Decomposition（分解）
- 判断・変更を "コンポーネント" に分解して扱う
  - 例：要件 / 影響範囲 / リスク / 実装案 / テスト案 / ロールバック案

## 2. Independent Judgments（独立評価）
- 仮説は最低3つ出す（単一仮説禁止）
- 各仮説に「最短の反証テスト」を1つずつ付ける

## 3. Mechanical Aggregation（機械的集約）
- 仮説スコア（各1-5）:
  - 整合性（症状/要件を説明できる）
  - 検証コスト（反証が安い）
  - 影響範囲（直した時に壊すリスク）
- 上位から検証し、証拠が揃うまで修正に入らない

## 4. Exception Logging（例外は記録必須）
- 例外対応（暫定パッチ等）をしたら、必ず理由と期限をログ化
- 次スプリントに"負債返済タスク"を自動で作る（このタスク内で作成）

# 📦 Deliverables（成果物）
- docs/decision/ADR-xxxx.md（設計判断ログ）
- docs/incident/INC-xxxx.md（バグ/障害なら）
- tests/（追加/更新したテスト）
- CHANGELOG or RELEASE_NOTE（必要なら）
- "Why" が残るコメント（コードだけでなく理由）

# 🔍 Constraints / Guardrails
- 変更範囲（ファイル/モジュール）を先に宣言する
- 既存設計（Router/Planner/Reranking等）を壊さない
- セキュリティ/個人情報/秘密情報の取り扱いを守る
- "動いた"だけで完了にしない。必ず再発防止テストを追加

# 🧪 Test Plan（先に書く）
- Unit:
- Integration:
- E2E:
- Regression（今回のバグを殺すテスト）:

# 🪜 Execution Plan（ステップ）
1) 現状観測（ログ/再現/入力）を整理（Observed / Expected）
2) 仮説3つ以上＋反証テスト
3) 最小変更で実装（1仮説＝1修正）
4) テストを追加して実行
5) 結果を要約し、ADR/INCを更新
6) 次の改善（フォロータスク）をBeadsで作成

# 🧾 Reporting Format（出力フォーマット）
- 進捗報告は以下で統一:
  - What I changed:
  - Evidence（テスト/ログ）:
  - Decision（なぜこの結論か）:
  - Remaining risks:
  - Follow-up tasks:

---

## バグ調査の場合

バグ調査や障害対応の場合は、別途 **`bug-triage-template.md`** のテンプレートを使用してください。

主な違い:
- バグ調査は「原因の特定」または「再現条件の確立」がゴール
- Fixed Sequence（順序固定）で進める
- Hypothesis Table（仮説表）が必須
- 再発防止テストが必須

---

## プロンプト例

### 通常タスクの場合
```
あなたはBeads運用のテックリードです。
次の入力（目的/制約/現状）から、上記テンプレートに従ってBeadsのタスク本文を生成してください。

入力:
- Objective: [タスクの目的]
- Context: [現状・背景]
- Constraints: [制約条件]
- Files touched (if known): [変更予定のファイル]
```

### バグ調査の場合
```
あなたはBeads運用のテックリードです。
次の入力から、bug-triage-template.mdに従ってバグ調査タスクの本文を生成してください。

入力:
- Objective: [原因の特定 または 再現条件の確立]
- Observed: [観測された現象]
- Expected: [期待される動作]
- Repro steps: [再現手順]
```
