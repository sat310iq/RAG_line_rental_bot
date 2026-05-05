# LINE 手動テストケース

Cloud Run 上の LINE Webhook に接続した公式アカウント（または検証用チャネル）で、**送信順どおり**に試す前提のチェックリストです。

## 事前条件

- LINE Developers の Webhook URL が、検証対象の Cloud Run（例: `rental-rag-poc`）の **`/webhook`** と一致している。
- Cloud Run に `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` / `OPENAI_API_KEY` 等が設定済み。
- ログ確認: Cloud Logging で `textPayload`（または `jsonPayload.message`）に本文が載る前提でフィルタする（環境により前者・後者が異なる場合あり）。

---

## 1. KB fast path（即答）

| ID | 送信するテキスト | 期待するざっくり挙動 | 確認メモ |
|----|------------------|----------------------|----------|
| FP-01 | `ガス料金を知りたい` | ガス会社・料金案内の即答（hit） | `kb_fast_path_hit`、意図 `生活_ガス料金` 付近 |
| FP-02 | `お湯が出ない` | 給湯・故障系の即答（hit） | 短文でも hit（`is_specific_even_if_short` 系） |
| FP-03 | `車庫証明` | 証明書系の即答（hit） | 短文・具体語 |
| FP-04 | `喫煙は可能ですか` | ペット不可など方針の即答（hit） | 意図が `ペット飼育の可否` 等の KB 行に寄る |

---

## 2. Clarification（短文）→ 例文どおり送信

| ID | 手順 | 期待 |
|----|------|------|
| CL-01 | `ガス` | 番号付き選択肢＋「上の 1〜3 の番号だけでも返信できます。」＋例文リスト（clarification） |
| CL-02 | 続けて例文のいずれかをそのまま送信（例: `お湯が出ない`） | 給湯故障の hit または妥当な即答 |
| CL-03 | `証明書` | clarification（例文・番号案内あり） |
| CL-04 | 続けて `車庫証明を発行したい` など | 証明書 hit |

---

## 3. Clarification → **番号だけ**で返信

（直前の bot メッセージが **同じ会話の clarification** であることが必須。別トピックの会話のあとでは無効。）

| ID | 手順 | 期待 |
|----|------|------|
| N-01 | `電気` → 続けて `1` | 料金・契約系の例に展開され、九州電力などの案内（hit または妥当な応答） |
| N-02 | `電気` → 続けて `2` | 停電系の例に展開され応答（`clarification_numeric_resolved` ログに `raw_text` / `resolved_text`） |
| N-03 | `電気` → 続けて `２`（全角） | `2` と同様に解決される（NFKC 後 1 桁） |
| N-04 | `ガス` → 続けて `1` | 選択肢 1 に対応する例文へ展開され、意図に沿った hit / 案内 |

---

## 4. 同一曖昧短文の再送（prior 補助）

| ID | 手順 | 期待 |
|----|------|------|
| R-01 | `ガス` → 続けて再度 `ガス` | **再度 clarification**（同じ曖昧語のだけでは hit にしない） |
| R-02 | `ガス` → `お湯が出ない` | 具体化なので **hit**（設備_ガス故障寄り） |

---

## 5. 番号の誤爆防止（clarification 直後でない）

| ID | 手順 | 期待 |
|----|------|------|
| E-01 | 会話の冒頭、何も説明なしで `1` だけ送信 | 番号展開**しない**（`clarification_numeric_resolved` が出ない想定）。miss または RAG・汎用応答 |
| E-02 | 通常の質問のあと、文脈なく `2` のみ | 同上 |

---

## 6. インターネット（選択肢 2 + 番号）

| ID | 手順 | 期待 |
|----|------|------|
| NET-01 | `ネット` または `インターネット` で clarification が返るまで短文を調整 | clarification（2 択＋番号案内） |
| NET-02 | 続けて `1` | プラン変更・問い合わせ系の例文に展開され応答 |

---

## 7. ログで見る項目（デプロイ後の受け入れ）

| 確認 | クエリ例（要・環境に合わせ `textPayload` / `jsonPayload.message` を選択） |
|------|-----------------------------------------------------------------------------|
| 番号解決 | `textPayload=~"clarification_numeric_resolved"` |
| fast path | `textPayload=~"kb_fast_path_(hit|clarification|miss)"` |
| ユーザー相関 | `textPayload=~"line_user_id"` または `Processing LINE message: line_user_id=` |
| 電気フロー | `textPayload=~"kb_fast_path_"` と `normalized_query` または `resolved_text` で絞る |

---

## 8. KB miss → RAG 時の `prior_clarification_*`（回帰・2026-05 修正）

**目的**: LINE handler 1 本目の `try_kb_fast_path` が **miss** のときに `RAGAnswerer.answer()` へ入る。ここで **直前の clarification 状態**（`prior_intent` / `prior_norm`）が内部の `try_kb_fast_path` に渡ると、**短語緩和**（`short` 解除）や意図一致時の挙動が handler と揃う。

**再現のコツ**

- 修正の差分が出やすいのは、**clarification 直後**に、1 本目の fast path が **hit でも clar でもなく miss** になる送り方（展開後テキストが閾値未満、または該当行なし等）のあと **RAG** に落ちるケース。
- Cloud Run **複数インスタンス**では `peek_prior_clarification` が別インスタンスに乗ると壊れる（セクション 9 既知制約）。**本項のテストは `min-instances=1` または低負荷・短時間に寄せる**と再現しやすい。

| ID | 手順（送信順） | 期待・見る観点 |
|----|----------------|----------------|
| **PC-01** | `電気` → clarification を確認 → 続けて **`1`**（半角） | `resolve_numeric_clarification_reply` が効けば `effective_text` が例文に置換。**handler が hit** なら RAG フォールバックなしで終了してよい。**handler が miss** のとき、ログで `before_reply: RAG answer starting` のあと、応答が「番号だけ」の誤解釈にならず、**展開後トピックに沿った内容**であること（prior 伝搬後の内部 fast path / RAG が破綻しないこと）。 |
| **PC-02** | `ガス` → clarification → **`お湯が出ない`** | 通常は handler で **hit**（内部 RAG に入らない）。**KB fast path が有効な環境で hit すること自体**は従来どおり。 |
| **PC-03** | `ガス` → clarification → **handler が miss になりやすい言い回し**を試す（例: データ次第で閾値ギリギリの言い換え、または一時的に `fast_path_enabled` が無いトピックへ寄せたテスト用文言）→ **RAG フォールバック** | Logging で `kb_fast_path_miss`（handler）→ `before_reply: RAG answer starting`。**修正前**は内部 `try_kb_fast_path` に prior が無く、`short` 緩和が効かず **再度 clarification** や空振りになりやすかった。**修正後**は `prior_clarification_intent` / `prior_clarification_normalized_query` が内部へ渡り、**意図が揃う hit や一貫した clar** に寄ること。 |
| **PC-04** | `証明書`（または `水道の件`）→ clarification → 続けて **具体文**（例: `車庫証明を発行したい`） | 多くは handler で hit。**miss のとき**も同様に RAG 内 prior の有無で二段目の分岐が変わるため、ログで `kb_fast_path_*` を追う。 |

**ログフィルタの例（Cloud Logging）**

- RAG フォールバック発動: `textPayload=~"before_reply: RAG answer starting"`
- 内部 fast path: `textPayload=~"kb_fast_path_(hit|clarification|miss)"`
- 番号解決: `textPayload=~"clarification_numeric_resolved"`

---

## 9. 既知の制約（メモ）

- **clarification の state**（直前の intent / 正規化クエリ / `numeric_queries`）は **インスタンスローカル**。Cloud Run の複数インスタンスでは、別インスタンスに振られたメッセージでは番号展開が効かないことがある（PoC 想定）。
- 負荷試験や本番同等の連続試験では、`min-instances` や単一インスタンスに近い条件で試すと再現しやすい。

---

## 改訂履歴

- 初版: KB fast path / clarification / 番号返信 / 同一曖昧再送 / ログ観測をカバー。
- 2026-05-04: セクション 8 を追加 — KB miss → RAG 時の `prior_clarification_*` 回帰テスト（handler と `RAGAnswerer.answer` の prior 伝搬確認）。
