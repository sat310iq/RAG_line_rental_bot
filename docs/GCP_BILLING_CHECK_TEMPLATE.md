# GCP 課金確認テンプレート（Option 1 後）

Billing Reports を開いたときに、**その場でコピペして記録・判定**できるチェックシートです。  
（Console のラベルは UI 更新で微妙に変わることがあるため、「SKU で内訳が見える」ことを優先してください。）

---

## ① 基本設定（最初に必ず）

- **期間:** 過去 7 日 **または** 30 日
- **表示単位:** 日次
- **フィルタ:**
  - **Project** = `line-webhook-poc-1767009745`（実プロジェクト ID に置き換え）
- **Group by:**
  - **SKU**（まずサービス別に見る場合は **Service** で俯瞰し、必要なら SKU まで展開）

---

## ② チェックシート（コピペ用）

### GCP 課金確認ログ（PoC 停止後）

#### 実行情報

- 実行日: YYYY-MM-DD
- 実行コマンド:

```text
bash deploy/suspend_and_trim_images.sh --yes \
  --delete-pubsub --delete-gcr-images --delete-ar-images --keep-latest 3
```

（実際に実行したフラグだけ残してよい。）

---

#### SKU 別課金（直近）

| サービス           | 状態 | 金額 | コメント |
| ------------------ | ---- | ---- | -------- |
| Cloud Run          |      |      |          |
| Pub/Sub            |      |      |          |
| Artifact Registry  |      |      |          |
| Cloud Storage      |      |      |          |
| その他             |      |      |          |

---

#### 判定

- [ ] 課金はゼロまたはほぼゼロ（成功）
- [ ] 微小課金のみ（許容）
- [ ] 想定外課金あり（要調査）

---

#### 次アクション

（例）

- なし
- AR 追加削除（`suspend_and_trim_images.sh` の dry-run → 本実行）
- GCS / Cloud Build 残骸の確認
- Billing アラート設定

---

## ③ 判定ルール

### 成功（理想状態）

| サービス           | 状態                       |
| ------------------ | -------------------------- |
| Cloud Run          | 0 円付近                   |
| Pub/Sub            | 0 円付近                   |
| Artifact Registry  | 大幅減または数十円レベル   |
| Cloud Storage      | 数円以下                   |

**結論:** 課金制御としては**成功に近い**。

---

### 許容（現実ライン）

| サービス           | 状態             |
| ------------------ | ---------------- |
| Artifact Registry  | 数十〜数百円     |
| Storage            | 数円程度         |

**結論:** **放置してよいライン**（運用コストとして許容）ことも多い。翌日・週次でもう一度だけ見てトレンドを確認。

---

### 要対応（異常）

#### ケース 1: Artifact Registry が高い

- 例: **¥500 以上**が継続（※直後の残存分は「今月すでに積み上がった分」で一時的に高く見えることがある）

**想定原因:** イメージがまだ残っている、または別リポジトリに溜まっている。

**対応:**

- `bash deploy/suspend_and_trim_images.sh --dry-run --delete-ar-images --keep-latest 3` で **DEL 候補**を再確認
- Console の Artifact Registry で **リポジトリ・パッケージの残数**を確認

---

#### ケース 2: Cloud Storage が高い

- 例: **¥100 以上**（プロジェクト規模による）

**想定原因:** Cloud Build 関連バケット、ログ、その他オブジェクトの肥大。

**対応:**

```bash
gsutil ls
gsutil du -sh gs://BUCKET_NAME
```

---

#### ケース 3: Cloud Run に課金

**想定原因:** 再デプロイ、`min-instances > 0`、トラフィックによる実行課金。

**対応:**

```bash
gcloud run services list --region=asia-northeast1
gcloud run services describe SERVICE_NAME --region=asia-northeast1 --format='yaml(spec.template.metadata.annotations,spec.template.spec.containerConcurrency,spec.template.spec.containers)'
```

---

#### ケース 4: 区分が分かりにくい「その他」

**想定原因:** 有効 API に紐づく従量、Logging、ネットワーク系 SKU など。

**対応:** Reports で **SKU 行を展開**し、金額の上位から特定する。

---

## ④ 時系列（グラフ）

### 見るポイント

- **整理スクリプト実行日**を境に、日次の棒が **下がる・平坦化する**か。

**正常（イメージ）:** 実行後に段差で下がる。

```text
███▇▆▂▁
```

**要確認:** 実行後も高止まり（別要因 or 残存ストレージ、レポートラグ）。

```text
███▇▆▆▆
```

---

## ⑤ 1 分判断フロー

1. Billing → Reports を開く
2. **プロジェクトで絞る**
3. **SKU（またはサービス）**で金額の**上位 1〜2 個**だけ見る

**判断:**

- **Artifact Registry だけ**が目立つ → イメージ整理の効果を時系列で確認（多くは許容〜成功寄り）
- **Storage だけ** → バケット・ビルド成果物を疑う
- **複数サービスが同程度** → SKU 展開で切り分け

---

## ⑥ 次の最適アクション（状況別）

| 状況           | アクション                               |
| -------------- | ---------------------------------------- |
| ほぼゼロに近い | なし、または月 1 回だけ再確認             |
| 少額が残る     | 放置 or 追加削除（コストと手間のトレード） |
| 想定外         | `bash deploy/check_gcp_resources.sh` を再実行 |

---

## ⑦ （オプション）再発防止

- Billing アラート（例: 月 **¥100** や予算の 50%）
- 月 1 回、このチェックシートだけ回す
- デプロイ手順に「PoC 用プロジェクト ID の確認」を固定で書く

---

## まとめ（Option 1 後の目安）

**Artifact Registry が、実行前より実質的に下がり（または数十円レベルで頭打ち）、他が追随していなければ成功扱いでよい**ことが多いです。  
**0 円保証ではない**ため、Logging / API / ストレージの微小額は Reports で SKU まで落として確認してください。

---

## 関連

- 整理スクリプト: [GCP_SUSPEND_AND_IMAGE_TRIM.md](GCP_SUSPEND_AND_IMAGE_TRIM.md)
- 停止・再開全体: [GCP_SUSPEND_AND_RESUME.md](GCP_SUSPEND_AND_RESUME.md)
