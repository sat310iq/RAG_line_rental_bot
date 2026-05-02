# LINE Webhook で返信が来ないときの調査手順

## ログの階層別確認方法（受信 → 処理 → 応答）

返信の有無を切り分けるときは、Cloud Run ログを次のステージ順に確認すると原因を絞り込みやすくなります。

| ステージ | 期待ログ例 | 補足 |
|----------|------------|------|
| **受信** | `LINE webhook received body_len=... events_count=1` | リクエストが Cloud Run に届いているか |
| **解析** | `Processing LINE message: text_preview=... has_reply_token=True` | テキストと reply token が取得できているか |
| **返信** | `LINE Reply API success: reply sent` | 応答が LINE に届いたか |
| **エラー** | `LINE Reply API error: status=400` など | token 失効・アクセストークン不正など |

どこまでのログが出ているかで、受信・署名・RAG・返信のどの段階で止まっているかを判断できます。

---

## 1. LINE 側の Webhook 設定（アプリ外）

| 確認項目 | 正しい例 | 誤り例 |
|----------|----------|--------|
| Webhook URL | `https://xxxx.run.app/webhook`（末尾に `/webhook` 必須） | `https://xxxx.run.app`（スラッシュなし） |
| Webhook の利用 | **ON** | OFF |
| メッセージタイプ | テキスト（"text"）で送信 | 画像・スタンプのみは未対応でスキップされる |

## 2. reply token の有効期限切れ（Cold Start）

- LINE の reply token は**約 30 秒**で失効する。
- Cloud Run がスケールゼロから起動する場合、初回リクエストで **Cold Start（15 秒以上かかることがある）** により、RAG 実行完了前に token が切れる可能性がある。

**再現確認**: 同じメッセージを**2回送る**。2回目は Warm 状態のため応答が返りやすい。

**ログでの確認**: `Reply token expired (400)` または `LINE Reply API error: status=400` かつ body に "invalid reply token" が出ていれば、ほぼこの要因。

**対策案**: Cloud Run で `min-instances=1` にすると Cold Start を避けられる（課金増）。

### Cold Start（最初の1リクエストが失敗する場合）

Cloud Run の **min-instances=0**（デフォルト）の場合、スケールゼロから起動するため、**最初の1リクエスト（Cold Start 時）は 10〜30 秒かかることがあります**。reply token の有効期限（約 30 秒）に間に合わず、返信が失敗することがあります。

**「最初の1回は失敗して当然」と割り切り、以下で対応してください。**

#### 解決策

- **もう一度同じメッセージを送ってください**（2回目は Warm 状態のため成功する可能性が高いです）
- 本番運用で Cold Start を避けたい場合は、Cloud Run の **min-instances=1** の設定を検討してください（常時1インスタンス起動のため課金が発生します）

## 3. ベクトルストア・KB の未初期化

- イメージ内の `data/vector_store/` が**空または存在しない**と、RAG が 0 件ヒットしフォールバックしか返らない。または RAG 初期化で例外になる可能性がある。
- ビルドコンテキストに `data/vector_store` を含めるには、**デプロイ前にローカルで再インデックス**が必要。

**再現確認**:
- Cloud Run ログで `Vector store initialized: deal=0 master=0` または `Vector store has 0 documents` が出ていないか確認。
- 出ている場合は、ローカルで `python3 scripts/reindex_vector_db.py` を実行したうえで、再度 `./deploy/deploy_webhook.sh` を実行する。

**デプロイ手順**:
1. `python3 scripts/reindex_vector_db.py` で `data/vector_store` を生成。
2. その後 `./deploy/deploy_webhook.sh` を実行（スクリプト内で `data/vector_store` の存在チェックあり）。

## 4. RAG は成功したが LINE Reply で 400

- **reply_token 失効**: 上記 2 と同様。
- **LINE Channel Access Token 失効**: LINE Developers でトークンを再発行し、Cloud Run の環境変数 `LINE_CHANNEL_ACCESS_TOKEN` を更新。
- **Cloud Run からの外部通信ブロック**: 通常はブロックされないが、VPC 等でアウトバウンド制限している場合は `api.line.me` への HTTPS を許可する必要がある。

**ログでの確認**: `LINE Reply API error: status=400 body=...` を開き、body のメッセージで原因を切り分ける。

## 5. メモリ不足でコンテナが強制終了（OOM）

RAG（Embedding・Chroma・LLM）の利用で **512 MiB では不足**することがあり、処理中に Cloud Run がコンテナを強制終了します。その結果、LINE には返信が返りません。

**ログでの確認**:  
- `Memory limit of 512 MiB exceeded with XXX MiB used`  
- `the container instance was found to be using too much memory and was terminated`

**対処**: Cloud Run のメモリを **1 GiB** に増やす。`deploy_webhook.sh` は 1Gi でデプロイするようにしてあります。既存リビジョンはコンソールで「リビジョンを編集」→ メモリを 1 GiB に変更して保存、または `./deploy/deploy_webhook.sh` で再デプロイしてください。

## 6. レスポンスが遅い

**要因**:
- **Cold Start**: min-instances=0 のとき、最初の1リクエストでコンテナ起動＋RAG 初期化（Chroma・Embedding 読み込み）で **10〜30 秒**かかることがある。
- **RAG パイプライン**: 検索（ベクトル＋BM25）→ リランク → LLM 生成で **数秒〜十数秒**かかる。

**対処**:
- **2回送る**: 1回目が遅い場合は同じメッセージを再送すると、Warm 状態で速く返ることがある。
- **本番で遅延を抑えたい場合**: Cloud Run の **min-instances=1** を検討（常時1インスタンス起動で Cold Start を回避。課金増）。
- **タイムアウト**: Cloud Run のリクエストタイムアウトは 60 秒。LINE の reply token は約 30 秒で失効するため、実質的には 30 秒以内に返信する必要がある。

---

## 今すぐできる最小再確認リスト（クラウドで応答が来ないとき）

| チェック項目 | 方法 |
|--------------|------|
| Webhook URL 末尾に `/webhook` があるか | LINE Developers Console の「Messaging API」→「Webhook URL」を確認 |
| Cloud Run ログに `LINE webhook received` があるか | Cloud Logging で `line-webhook` のログを開き、メッセージ送信時刻前後に該当ログがあるか確認 |
| `Processing LINE message: ...` が出ているか | 同上。出ていればイベント解析まで到達している |
| `LINE Reply API success` または `LINE Reply API error` があるか | 返信試行の成否を確認。error の場合は status と body を確認 |
| `RAG answer failed` が出ていないか | RAG 内で例外が出ているとフォールバック返信になる。出ている場合はスタックトレースで原因特定 |
| ベクトルストアが 0 でないか | ログの `Vector store initialized: deal=N master=M` で N, M が 0 でないか確認 |
| Cloud Run の `LINE_CHANNEL_ACCESS_TOKEN` が有効か | LINE Developers の Channel Access Token と一致しているか。必要なら再発行して環境変数を更新 |

---

## 正常時のログの流れ（例）

**正常に返信されたとき**は、Cloud Run ログに以下のような時系列で出力されます。この流れになっていれば、LINE 側に応答は届いていると判断できます。

```
LINE webhook received body_len=1287 events_count=1
Processing LINE message: text_preview=給湯器が壊れました has_reply_token=True
LINE Reply API success: reply sent
```

（RAG 実行は上記の「Processing」と「LINE Reply API success」のあいだで行われ、ログには DEBUG 等で出る場合があります。）

**どこで止まっているか**で、上記のどの要因（環境変数・署名・Cold Start・ベクトルストア・Reply API 失敗）に該当するか切り分けてください。
