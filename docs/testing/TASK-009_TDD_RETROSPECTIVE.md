# TASK-009 TDD 振り返りサマリ

更新日: 2026-05-06
対象: TASK-009（B-6監査ログ）

## 今回うまく機能した点

- Slice 1でREDを検出し、`reason=no_judgment_phrase` と期待 `contract_ref` の差分を早期発見できた。
- Slice 3でREDを検出し、ロガー名不一致を特定できた。テストが仕様として機能した。
- Slice 5のREFACTOR時に回帰を検出し、`contract_ref_hit and not judgment_hit` の条件に収束できた。

## 要注意ポイント

- Slice 2 / Slice 4 は即GREENだったため、次回は「なぜREDにならなかったか」を明示的に確認し、テストコメントや実装メモに記録する。

## rental_rag におけるTDD活用マップ

- 新機能追加（TASK-007/008）: フル垂直スライス（推奨）
- バグ修正: `/diagnose` → 再現テストでRED → 最小修正でGREEN
- 既存コードのリファクタ: 先に回帰テストを用意 → REFACTOR → 全GREEN確認
- 閾値調整: パラメータ化テストでRED→GREEN
- KB追加（Master TXT更新）: KBヒット率テストでRED→GREEN

## TASK-007（タイムアウト対策）への適用案

- Slice 1: タイムアウト再現テスト（RED）  
  `test_deal_search_completes_within_timeout()`
- Slice 2: タイムアウト閾値調整でGREEN
- Slice 3: Cloud Run設定（最小インスタンス1）でcold start影響を低減  
  ※ cold startはテストでなくintegration / ログ監視で補完
- Slice 4: タイムアウト処理のREFACTOR（全GREEN後）

## TASK-008（フォールバック削減）への適用案

- Slice 1: フォールバック発生クエリの再現テスト（RED）  
  `test_query_X_returns_kb_answer_not_fallback()`
- Slice 2: KBエントリ追加でGREEN
- Slice 3: 同パターンを「1クエリ = 1スライス」で反復

## ルール追記案（.cursor/rules）

TDD Rules（mattpocock/tdd準拠）:

- 実装前に必ずREDテストを書く
- 1スライス = 1テスト → 1実装（垂直スライス厳守）
- RED中はリファクタリングしない
- パブリックIF経由のみテストする（内部関数・privateメソッド禁止）
- 即GREEN時は「なぜREDにならなかったか」を確認し記録する
- REFACTOR後は必ず全テスト回帰確認する

## 次のアクション

1. `kanban.md` 更新 + TASK-009コミット
2. Cloud Runデプロイ（00021）
3. TASK-007（タイムアウト対策）をTDDで実装
4. TASK-008（フォールバック削減）をTDDで実装
5. LINEテスト（61件）を実行
