# Eval Log — rental_rag_poc
> Framework v2対応 | Superforecasting / Brier Score接続
> 更新タイミング：スプリント終了時 / Escalation発生時

---

## 関連ファイル
- `docs/kanban.md` — タスク管理
- `docs/research.md` — 技術調査蓄積
- `docs/decisions/` — ADR置き場

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
- **最優先:** 活用形不一致問題（BACKLOG化）— "動きません/壊れました" 等の `-ます`/`-ました` 語尾に対応する secondary キーワード整備
- 仮説: 頻出16ミスの上位5件に secondary を追加するだけで Fallback Rate を 20% 以下に抑えられる見込み

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
