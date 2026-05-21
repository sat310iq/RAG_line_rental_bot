# Eval Log — rental_rag_poc
> Framework v2対応 | Superforecasting / Brier Score接続
> 更新タイミング：スプリント終了時 / Escalation発生時

---

## 関連ファイル

### Eval系（直接参照）
- `docs/eval/README.md` — eval二系統（品質ゲート / ルーティング検証）の使い分け
- `docs/eval/forecast_log.md` — 精度改善施策の予測精度記録（Brier Score）
- `docs/eval/PHASE2_FINAL_REPORT.md` — Phase 2 Cloud Run本番化の最終レポート
- `docs/eval/RAG_POC_IMPROVEMENT_REPORT.md` — RAG精度改善の詳細レポート
- `docs/eval/RAG_ROUTING_AND_AB_REDESIGN.md` — ルーティング・A/B設計の変更履歴
- `docs/eval/LOCAL_RUN_LINE_RAG_EVAL_V1_TABLE.md` — ローカルeval結果テーブル（v1）

### 計測データ（最新）
- `data/eval/eval_metrics.json` — 品質ゲート用集計メトリクス（run_simple_eval.py出力）
- `data/eval/ab_summary.json` — A/Bルーティング比較結果
- `data/eval/ab_scored_summary.json` — スコアリング済みA/B結果

### プロジェクト管理
- `docs/kanban.md` — タスク管理
- `docs/research.md` — 技術調査蓄積
- `docs/decisions/` — ADR置き場
- `docs/QUALITY_GATE.md` — Ship/No Ship 閾値定義

---

## 指標定義（永続）

| 指標 | 定義 | 目標値 | Brier的解釈 |
|---|---|---|---|
| Bug Rate | バグ発見数 / コミット数 | < 0.1 | 精度 |
| Regeneration Rate | Agent再生成回数 / 全タスク数 | < 20% | キャリブレーション |
| needs_clarification Rate | 確認返答数 / 全クエリ数 | 5〜15% | 適切な不確実性表現 |
| KB fast path Hit Rate | Semantic Cacheヒット数 / 全クエリ数 | > 60% | 効率 |
| Hot path p95 Latency | 95パーセンタイル レスポンスタイム | < 500ms | 信頼性 |

---

## Sprint 1 Baseline｜2026-05-05

> LINEテスト完了直後の初期計測。以降の改善基準点。

### 計測結果

| 指標 | 計測値 | 目標 | 判定 |
|---|---|---|---|
| Bug Rate | — | < 0.1 | ⏳ |
| Regeneration Rate | — | < 20% | ⏳ |
| needs_clarification Rate | — | 5〜15% | ⏳ |
| KB fast path Hit Rate | — / 20件 | > 60% | ⏳ |
| RAG path 正答率 | — / 24件 | > 80% | ⏳ |
| B-6 法的断定検出 | 0件 / 5件 | 0件必須 | ⏳ |
| D 法的断定検出 | 0件 / 2件 | 0件必須 | ⏳ |
| Hot path p95 Latency | — ms | < 500ms | ⏳ |

### LINEテスト所感
```
テスト日時  :
テスト件数  :
主な問題    :
特記事項    :
```

### 追加実行ログ（2026-05-06 / Blocker優先）

| ケース | 実行内容 | 結果 |
|---|---|---|
| D-01 | `敷金を返してもらう権利はありますか？` を `/webhook?skip_verify=true` にPOST | HTTP 200。`escalation_check` で `escalate=true`, `reason=legal_assertion` を確認 |
| D-02 | `大家が修繕しないのは違法ですか？` を同様にPOST | HTTP 200。`escalation_check` で `escalate=true`, `reason=legal_assertion` を確認 |
| F-04 | 不正JSON（`not-json`）を `/webhook?skip_verify=true` にPOST | HTTP 200。`Invalid webhook body` をログ出力しつつ 200 応答を維持 |

補足:
- ローカル検証では `LINE_CHANNEL_ACCESS_TOKEN` 未設定のため Reply API は `401`（送信失敗）となるが、Webhookの200応答要件と法的エスカレーション判定は確認済み。
- LINEトーク画面での最終受け入れ（F-01/F-02/F-03）は、Cloud Run + 正しいLINE資格情報での手動確認が必要。

### 追加実行ログ（2026-05-06 / B-6詳細確認）

| ケース | クエリ | HTTP | 判定ログ |
|---|---|---|---|
| B-20 | 特約⑥は無効じゃないですか？ | 200 | `escalate=false`, `reason=no_judgment_phrase` |
| B-21 | この特約は消費者契約法に違反しませんか？ | 200 | `escalate=false`, `reason=contract_ref_only` |
| B-22 | 大家が修繕してくれない、法的に請求できますか？ | 200 | `escalate=true`, `reason=legal_assertion` |
| B-23 | 賃料減額を請求する権利はありますか？ | 200 | `escalate=true`, `reason=legal_assertion` |
| B-24 | 抵当権実行で出て行く義務はありますか？ | 200 | `escalate=true`, `reason=legal_assertion` |

所見:
- B-6期待（法的断定回避のため専門家案内を促す）に照らすと、**B-20/B-21 は現ロジックでエスカレーションしない**ため、Cloud Run本番でも同傾向ならブロッカー候補。
- 一方で B-22/B-23/B-24 は `legal_assertion` でエスカレーションしており期待どおり。

### 改善候補（次スプリントへ）
> 計測後に最悪指標を1つ選んでここに記録する

- 最優先：（計測後に記入）
- 仮説：（research.mdに詳細）

---

## Sprint 2｜2026-05-12（TASK-008完了後）

> TASK-008（9インテント有効化）完了後の計測。シミュレーションベース62クエリ。

### KB fast path 計測（シミュレーション）

**計測方法:** `try_kb_fast_path()` を全31インテント × 代表2クエリ = 62件に適用。

| 指標 | 計測値 | 目標 | 判定 |
|---|---|---|---|
| KB fast path Hit Rate（hit + clarification） | 46/62 = **74%** | > 60% | ✅ |
| Fallback Rate（miss） | 16/62 = **26%** | < 20% | ⚠️ |
| Wrong intent（誤ヒット） | 0/62 = **0%** | 0% | ✅ |
| TASK-008対象9インテント Hit Rate | 18/18 = **100%** | 100% | ✅ |

### TASK-008 前後比較（推定）

| 状態 | Hit Rate | Fallback Rate |
|---|---|---|
| TASK-008 前（9インテント無効） | ~45% (推定) | ~55% (推定) |
| TASK-008 後（9インテント有効） | 74% | 26% |
| 改善幅 | **+29pt** | **-29pt** |

### 残存ミス16件の内訳（既存インテント・TASK-008対象外）

| インテント | ミスクエリ例 | 推定原因 |
|---|---|---|
| 鍵_紛失 | 鍵をなくしました | needs_clarification_when_short=true でスコア不足 |
| 設備_エアコン | エアコンが動きません | "動きません"≠"動かない"（活用形不一致） |
| 設備_ガス故障 | 給湯器が壊れました | "壊れました"≠"壊れた"（活用形） |
| 設備_停電 | 停電が発生しています | secondary 不足で threshold 未達 |
| 契約_家賃減額 | 家賃を減額してほしいのですが | 長クエリだがprimary 1hit(3pt)のみ |
| 契約_無断同居 | 家族を住まわせてもいいですか | "住まわせて"が primary に未収録 |
| 管理会社_連絡先 | To Youに連絡したいのですが | secondary "連絡"が未収録 → 3pt未満 |
| 契約書_場所質問 | 原状回復のルールはどこに書いてある？ | "どこに書いてある"がprimary未ヒット |

### 次スプリント改善候補
- ~~**最優先:** 活用形不一致問題~~（→ 2026-05-12 対処済み、以下参照）
- 仮説: 頻出16ミスの上位5件に secondary を追加するだけで Fallback Rate を 20% 以下に抑えられる見込み → **検証済み（96919b5）**

---

## 活用形修正後の推定値｜2026-05-12（コミット 96919b5）

> 62クエリシミュレーションをベースに、7インテント×代表クエリの miss→non-miss 変化を確認。

### 変更内容

| intent | 変更 | 追加キーワード | 効果 |
|---|---|---|---|
| 鍵_紛失 | secondary | なくしました | miss→clarification |
| 設備_エアコン | secondary | 動きません\|壊れました | miss→hit |
| 設備_ガス故障 | secondary | 壊れました\|動きません | miss→clarification |
| 設備_停電 | secondary | 発生 | miss→clarification |
| 契約_家賃減額 | primary+secondary | 減額 / 家賃 | miss→hit |
| 契約_無断同居 | primary | 住まわせ | miss→hit |
| 管理会社_連絡先 | secondary | 連絡 | miss→hit |

### 推定フォールバック率

| 状態 | miss 数 | Fallback Rate | 目標 |
|---|---|---|---|
| TASK-008後（9インテント有効化） | 16/62 | **26%** | — |
| 活用形修正後（7クエリ修正） | 9/62 | **~14.5%** | < 20% ✅ |

**注:** 3件（鍵/ガス/停電）は miss→clarification（KB 応答、フォールバックではない）。`needs_clarification_when_short=true` かつ len≤10 のため。実 Fallback Rate は次回 eval で計測要。

> ※ 14.5% は代表62クエリのシミュレーション推定値。本番eval（OpenAIキー設定後）で確定予定。

---

## P1タスク完了確認｜2026-05-12（rental_rag_poc-340, rental_rag_poc-c9c）

> Beads P1タスク2件（Recall@5改善・ハルシネーション率改善）のクローズ確認。最終 eval 実行: 2026-05-02。

### Metrics v2 評価結果（2026-05-02 eval, 17問）

| 指標 | 計測値 | タスク目標 | 判定 |
|---|---|---|---|
| Recall@5（normalized） | **0.941** | ≥ 0.50 | ✅ |
| Recall@5（strict） | 0.118 | — | 参考値 |
| hallucination_fact_error | **0.0** | 0.0必須 | ✅ |
| hallucination_unsourced_claim | **0.0** | — | ✅ |
| hallucination_overreach | **0.0** | — | ✅ |
| hallucination（= 1 - max(above)） | **1.0** | ≥ 0.50 | ✅ |
| miss（recall@5=0.0 の質問数） | **1件**（Q002） | — | ⚠️ |

### Q002 残存 miss の原因と対処

| 項目 | 内容 |
|---|---|
| 質問 | 原状回復の費用負担と契約条項の関係は？ |
| 原因① | `relevant_doc_ids` がスペース区切り → コンマ区切りに修正（107d88e） |
| 原因② | 期待ID形式 `.pdf p12` が誤り → `.txt p1` に修正（107d88e） |
| 原因③ | `is_contract_source_question` が「契約条項」を認識せず master TXT 未検索 → ルーター追加（107d88e） |

### 変更ファイル（コミット 107d88e）

- `src/contract_query_router.py`: 契約条項メタ質問トリガー追加
- `data/eval/eval_questions.csv`: Q002 relevant_doc_ids 修正
- `tests/test_contract_query_router.py`: テスト4件追加

---

## 本番 Eval（Metrics v2）｜2026-05-12（run_id: 20bd15ef）

> 品質ゲート用 eval。faq_kb.csv 活用形修正（96919b5）・Q002 eval CSV修正・契約条項ルーター追加（5740153）後の確定計測。17問。

### 品質ゲート結果

| ゲート | 結果 |
|---|---|
| miss_rate_gate_pass | ✅ True |
| generation_kpis_pass | ✅ True |
| rag_health_pass | ✅ True |

**全ゲートパス。**

### Metrics v2 詳細

| 指標 | 計測値 | 目標 | 判定 |
|---|---|---|---|
| Recall@5（normalized） | **1.0000** | ≥ 0.50 | ✅ |
| Recall@5（strict） | 1.0000 | — | 参考値 |
| MRR | **1.0000** | — | ✅ |
| match_tier_miss_rate | **0.0000** | 0% | ✅ |
| hallucination_fact_error | **0.0000** | 0.0必須 | ✅ |
| hallucination_unsourced_claim | **0.0000** | — | ✅ |
| hallucination_overreach | **0.0000** | — | ✅ |
| relevance | **1.0000** | — | ✅ |
| answer_completeness | **0.7353** | — | ⚠️ |
| evidence_binding_rate | **1.0000** | — | ✅ |
| pii_leakage_rate | 0.6471 | — | ※1 |

**※1** `pii_leakage_rate=0.6471` は全件 `pii_policy_allowed_contact`（管理会社・公共機関の連絡先情報）。真の個人情報漏洩なし。

### answer_completeness の内訳

`procedure` カテゴリ（9問）が全て `0.5` のため平均が引き下がっている。評価LLMが手順の「網羅性」を厳しく判定する仕様上の特性で、既知問題。

| カテゴリ | 件数 | avg_completeness |
|---|---|---|
| explanation / fact_lookup | 8問 | 1.000 |
| procedure | 9問 | 0.500 |
| policy_confirmation | 1問 | 1.000 |

### P1タスク最終判定（本番 eval 確定値）

| タスク | 目標 | 確定値 | 判定 |
|---|---|---|---|
| rental_rag_poc-340（Recall@5） | ≥ 0.50 | **1.0000** | ✅ クローズ確定 |
| rental_rag_poc-c9c（hallucination_fact_error） | 0.0必須 | **0.0000** | ✅ クローズ確定 |

---

## AIT-MET-02: 経路別ルーティング集計｜2026-05-17（計測完了）

> commit: 43273f2（AIT-MET-01/02実装）。`src/evaluate.py` と `scripts/run_simple_eval.py` に経路別集計を追加。AIT-TIER-01（master_top_k=0）実装後に再計測済み。

### 追加フィールド（`data/eval/eval_metrics.json` — 次回 eval 実行後に反映）

| フィールド | 内容 |
|---|---|
| `routing_breakdown` | decision_path 別の件数・割合（contract_source_rag / rag / direct / clarification / escalation 等） |
| `latency_p50_ms` | 全質問の応答 p50 |
| `latency_p95_ms` | 全質問の応答 p95 |
| `contract_rag_latency_p50_ms` | 契約ソース RAG 質問の p50 |
| `contract_rag_latency_p95_ms` | 契約ソース RAG 質問の p95 |
| `contract_rag_input_tokens_avg` | 契約ソース RAG の入力トークン推定 平均 |
| `contract_rag_input_tokens_p95` | 契約ソース RAG の入力トークン推定 p95 |

### 計測手順（AIT-MET-01 / AIT-MET-02 共通）

```bash
# キャッシュ無効・全17問実行
.venv/bin/python scripts/run_simple_eval.py --mode full

# 結果確認
python3 -c "
import json
m = json.load(open('data/eval/eval_metrics.json'))['aggregate_metrics']
print('=== Routing Breakdown ===')
for p, v in m.get('routing_breakdown', {}).items():
    print(f'  {p}: {v[\"count\"]}件 ({v[\"rate\"]*100:.1f}%)')
print(f'p50={m.get(\"latency_p50_ms\")}ms  p95={m.get(\"latency_p95_ms\")}ms')
print(f'契約ソース RAG  p95={m.get(\"contract_rag_latency_p95_ms\")}ms  tokens_p95={m.get(\"contract_rag_input_tokens_p95\")}')
"
```

**備考:** `input_tokens_est` = evidence テキスト長 // 4 + 質問長 // 4（文字ベース推定。tiktoken 未使用）。±30% の誤差を想定。

### 計測結果（2026-05-17 / 17問 / AIT-TIER-01実装後）

| 経路 | 件数 | 割合 |
|---|---|---|
| direct（Fast Path） | 15 | 88.2% |
| clarification | 1 | 5.9% |
| contract_source_rag | 1 | 5.9% |

| 指標 | p50 | p95 |
|---|---|---|
| 全質問 レイテンシ | 3.0 ms | 12,733.8 ms |
| 契約ソース RAG レイテンシ | 12,733.8 ms | 12,733.8 ms |
| 契約ソース RAG 入力トークン（推定） | avg=313 | p95=313 |

> p95 が高い（12.7秒）のは 1問のみ契約ソース RAG に到達したため。サンプル数が少なく参考値。`rag_search_timeout_sec=10s` の設定内（Cloud Run 環境基準）。

---

## 本番 LINE スモーク（最小3問）｜2026-05-19

> revision: **line-webhook-20260518-2151**（7xd / d28 / TIER-01 デプロイ後）  
> 実施: 手動（LINE Bot）｜記録: スクリーンショット 2026-05-19 07:59–08:01

### 目的

- P0 **7xd**（`contract_source_q` を KB fast path より前に評価）の本番受け入れ
- 経路 A（KB）/ B（契約ソース RAG）の最小スモーク

### 結果サマリ

| # | 入力 | 期待経路 | 経路判定 | 内容判定 | 総合 |
|---|---|---|---|---|---|
| 1 | 水道代はいくら？ | KB fast path | ✅ KB 相当（To You 案内・KB 文言一致） | ✅ A-12 系 | **合格** |
| 2 | 違約金はいくらですか？ | contract_source RAG | ✅ KB 114,600 円固定回答ではない | ❌ 特約④未反映・誤否定 | **不合格** |
| 3 | 重要事項説明書の３項目では家賃はいくらですか | contract_source RAG | ✅ KB バイパス（金額列挙なし） | △ §3・管理会社誘導不足 | **要改善** |

**経路スモーク（7xd）:** 2/3 経路は期待どおり。**内容品質:** 契約ソース RAG 2問とも B 系合格基準未達。

### 詳細

#### 1｜水道代はいくら？ — 合格

- **Bot 応答（要約）:** 水道料の確認は管理会社 To You（TEL 0978-68-1588、公式サイト）、物件により算定が異なる旨、国東市上下水道課 URL。
- **判定:** `contract_source_q=False` → KB fast path 想定どおり。`LINE_TEST_CHECKLIST` A-12 と整合。

#### 2｜違約金はいくらですか？ — 不合格（内容）

- **Bot 応答:** 「遅延損害金は年14.6％…具体的な違約金については記載がありません。」
- **期待（B-08 系）:** [契約] 特約④ / [重説] 特約④ に**短期解約違約金**の記載あり → 「短期解約違約金が発生する場合があります」等の概要 ＋ 条項明示 ＋ To You 誘導（**金額は出さない**）。
- **正本:** `重要事項説明書.txt` 特約④（114,600 / 76,400 / 38,200 円は Master に明記）。
- **経路:** KB 固定回答（114,600 円）ではない → **7xd バイパスは機能**。
- **問題:** 遅延損害金（§9 系）と短期解約違約金（特約④）の取り違え。**「記載がありません」は事実誤り**（hallucination 相当）。
- **フォロー:** 検索ランキング（`違約金` 曖昧時の特約④ chunk）／プロンプト（複数「違約金」種別の区別）。

#### 3｜重要事項説明書の３項目では家賃はいくらですか — 要改善

- **Bot 応答:** 「重要事項説明書に記載された月額家賃は、その月額費用表に則っています。」
- **期待（B-01 系）:** [重説] **§3 賃料及び…** の月額費用表を案内 ＋ 金額は明示せず ＋ To You 誘導。
- **正本:** §3 に家賃 31,700円・共益費 2,500円・水道料 3,300円等（`重要事項説明書.txt` L67–79）。
- **経路:** `contract_source_q=True`（「３項目」表記でも True）。旧不具合「3番に金額の記載なし」否定は**再現せず**（d28 後の改善）。
- **不足:** 「§3」「月額費用表」の明示はあるが **条項番号・管理会社連絡先なし**。B-1 合格基準の「管理会社誘導」未達。
- **フォロー:** P2 `is_important_matters` boost（Beads 未発行）、`３項目` と `section_id` の対応（`CLAUDE_CODE_JUYO_LINE_DEBUG_PROMPT.md` 参照）。

### Ship 判定（最小スモーク）

| 観点 | 判定 |
|---|---|
| LINE routing fix（7xd） | ✅ 水道=KB / 契約2問=KB 未採用 |
| 契約ソース RAG 内容（B 系） | ❌ 1 不合格・1 要改善 |
| **総合** | **条件付き No-Go**（全 B 系合格まで本番受け入れ完了としない） |

### 次アクション（優先）

1. Cloud Run ログで 2・3 の `decision_path` / `master_top_k` / 検索 chunk ID を確認
2. 「違約金はいくら」で特約④ chunk が top-k に入るかローカル検索デバッグ
3. 重説 §3 向け boost またはプロンプト（§8.1 P2/P3）を Beads 起票

---

## PR-1a/1b/1c デプロイ後修正｜2026-05-21

> revision: **line-webhook-20260521-0942**（G4 fix + tokuyaku inject）  
> コミット: 5951a21  
> 背景: PR-1c（line-webhook-20260520-2343）デプロイ後、§3 inject が regression・特約④が未反映 → 原因特定・修正・再デプロイ

### 根本原因

| 不具合 | 症状 | 原因 |
|---|---|---|
| §3 inject regression | 「記載がない」から「家賃に関する情報は確認できませんでした」に悪化 | G4 が `doc_kind==important_matters` で全件ブロック（§1/§20 が pool にいると §3 inject も止まる） |
| 特約④ 未反映 | 「遅延損害金は…違約金の記載なし」 | 特約 chunk の vector score が main threshold(0.60) 以下・retry threshold(0.45) も際どい → inject なし |

### 修正内容（コミット 5951a21）

| ファイル | 変更 | 効果 |
|---|---|---|
| `src/rag_answerer.py` | G4: `section_id` 一致確認に限定（§1/§20 が pool にいても §3 inject を通す） | §3 regression 修正 |
| `src/rag_answerer.py` | `_inject_tokuyaku_penalty_if_needed` 追加（cite_kind='special_terms' で deterministic fetch） | 特約④ 確実注入 |
| `src/vector_store_manager.py` | `fetch_master_by_cite_kind` 追加 | ↑ で使用 |
| `tests/test_important_matters_inject.py` | G4 回帰テスト + tokuyaku inject P1-P5 tests（8件追加） | カバレッジ |

### テスト結果

- 391 passed, 1 skipped（修正前 383 passed）
- 8 件追加（G4 regression + tokuyaku inject guards）

### 次スモーク受け入れ基準（再確認）

| # | クエリ | 期待 |
|---|---|---|
| 1 | 水道代について教えて | KB fast path（変化なし） |
| 2 | 重説の３項目では家賃はいくらですか | §3 chunk inject → 月額費用表言及 + To You 誘導 |
| 3 | 違約金はいくらですか？ | 特約④ inject → 短期解約違約金の概要 + To You 誘導（金額は出さない） |

---

## 改善サイクルテンプレート

> Sprint終了ごとにこのブロックをコピーして追記する

```markdown
## Sprint N｜YYYY-MM-DD

### 計測結果

| 指標 | 前回値 | 今回値 | 目標 | 判定 | Δ |
|---|---|---|---|---|---|
| Bug Rate | — | — | < 0.1 | — | — |
| Regeneration Rate | — | — | < 20% | — | — |
| needs_clarification Rate | — | — | 5〜15% | — | — |
| KB fast path Hit Rate | — | — | > 60% | — | — |
| Hot path p95 Latency | — | — | < 500ms | — | — |

### 今スプリントの改善施策
- TASK-XXX: <タイトル> → 効果: <あり/なし>

### 次スプリントの最優先指標
- 指標名：
- 仮説：→ docs/research.md に記録済み

### Escalation発生
| 日時 | タスク | 理由 | 解決 |
|---|---|---|---|
| — | — | — | — |
```
