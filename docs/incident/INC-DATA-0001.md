# INC-DATA-0001: 評価データセットの期待値誤り（restoration_cost）

## 概要

評価データセット（`eval_questions.csv`）のQ004「原状回復の費用負担と契約条項の関係は？」において、存在しないFAQ intent `restoration_cost`を期待値として使用していた問題。

## 観測結果

- **質問**: 「原状回復の費用負担と契約条項の関係は？」
- **期待ID**: `restoration_cost,contract.pdf p12`
- **問題**: `restoration_cost`というFAQ intentが`faq_kb.csv`に存在しない
- **実際のFAQ intent**: `契約_原状回復`（実際に存在するintent）

## 原因分析

評価データセット作成時に、FAQ intentの存在確認が行われていなかった。

## 修正内容

`eval_questions.csv`のQ004行を修正：

**修正前**:
```csv
原状回復の費用負担と契約条項の関係は？,multi,"faq,pdf",FAQ002 contract.pdf p12,"restoration_cost,contract.pdf p12",...
```

**修正後**:
```csv
原状回復の費用負担と契約条項の関係は？,multi,"faq,pdf",FAQ002 contract.pdf p12,契約_原状回復 グランマーレ大分空港契約書.pdf p12,...
```

- `restoration_cost` → `契約_原状回復`（実際のFAQ intent）
- `contract.pdf p12` → `グランマーレ大分空港契約書.pdf p12`（暫定修正、ADR-0004参照）

## 影響

- ID Normalization Success Rateが低下していた（修正前: 85%、修正後: 100%）
- 評価結果の信頼性が損なわれていた

## 再発防止策

1. **評価データセット作成時の検証プロセス**:
   - FAQ intentの存在確認を必須化
   - `faq_kb.csv`の`intent`列と照合するスクリプトを作成
   - CI/CDパイプラインに組み込む

2. **ID Mapperの強化**:
   - 存在しないFAQ intentが指定された場合、警告を出力
   - 評価実行時に自動検証

## 関連

- **INC-EVAL-0001**: 評価設計の修正（ID Normalization）
- **ADR-0004**: CSV暫定修正のADR

## ステータス

✅ **解決済み** (2026-02-03)
