# 実装まとめ：LINE → Cloud Run RAG PoC

本文書は、賃貸RAG PoC を **LINE Webhook 経由で Cloud Run 上にデプロイし、LINE 返信・（設計上は）Slack 通知までを目指した一連の実装** の総括である。うまくいった点、課題、未解決点、次回以降のフィードバックと再開時の着手点をクリティカルにまとめる。

---

## 1. 実装のスコープと成果物

### 1.1 対象範囲

- **LINE**: ユーザーが送ったテキスト → Webhook（Cloud Run）→ RAG 回答 → LINE に返信。
- **GCP**: Cloud Run（line-webhook）、ビルドは Cloud Build、コンテナは GCR。オプションで Pub/Sub → line-worker → Slack の経路を設計したが、**line-worker は未デプロイ**。
- **ローカルとの関係**: 「ローカルで確認した振る舞いをそのままクラウドにデプロイする」をルールとして固定し、設定・データの差分を文書化した。

### 1.2 主な成果物（コード・設定・ドキュメント）

| 種別 | 内容 |
|------|------|
| コード | LINE handler の堅牢化（try/except 全体、RAG 失敗時のフォールバック返信、reply token ログ、エラー時メッセージを `get_config().fallback_message` に統一）、Reply API エラー時の payload プレビューログ、VectorStoreManager 起動時の deal/master 件数ログ、get_collection_counts の例外時キー統一（deal/master） |
| 設定 | `config.py` の既定値をローカルに合わせて統一（CSV_SCORE_THRESHOLD=0.40, RAG_RETRIEVAL_K=16, OPENAI_MODEL=gpt-4o-mini）、env.example の RAG_RETRIEVAL_K=16、faq_kb.csv の生活_ガスに「給湯器\|給湯」追加 |
| デプロイ | deploy_webhook.sh（事前チェック・1Gi メモリ）、deploy_all.sh（事前チェック・.env.gcp 読込・Webhook→Worker→Pub/Sub の順）、scripts/deploy_webhook_build_only.sh、deploy/README.md（Cloud Build 説明・ビルド/反映の分割）、.gitignore に deploy/.env.gcp |
| ドキュメント | LOCAL_VS_CLOUDRUN.md（設定差分・揃え方）、LINE_TROUBLESHOOTING.md（ログ階層・Cold Start・ベクトルストア・正常時ログ）、RAG_ペット・ガス該当なし分析.md（該当なしの原因・確認項目・対処）、AGENTS.md の「ローカル＝クラウドのデプロイルール」、.cursor/rules/local-equals-cloud.mdc |

---

## 2. うまくいった点

- **LINE Webhook の Cloud Run デプロイ**: line-webhook のビルド・デプロイは成功し、Service URL が発行され、環境変数（OPENAI_API_KEY, LINE_CHANNEL_* 等）を設定すれば LINE からメッセージを受信し、RAG 回答を返信する流れは一応成立した。
- **ローカル＝クラウドのルール化**: 設定の既定値を env.example と一致させ、デプロイ前に reindex してからビルドする手順と「差分をコードに埋め込まない」方針を AGENTS.md と Cursor ルールに明文化した。次回以降のデプロイ判断がしやすくなった。
- **デプロイの分割と自動化**: ビルドのみ実行するスクリプトと deploy/README.md により、時間のかかるビルドと反映を分離できる。deploy_all.sh で gcloud 事前チェックと .env.gcp の読込を行い、Cursor ターミナルからワンコマンドでデプロイ可能にした。
- **LINE 周りの堅牢性**: RAG 失敗時や例外時にフォールバック返信で「既読だけ」を防ぎ、reply token の有無ログ・Reply API エラー時の payload プレビュー・Cold Start の説明を LINE_TROUBLESHOOTING にまとめた。デバッグの切り分けがしやすくなった。
- **該当なしの原因の構造化**: ペット・ガスで「該当する回答なし」になる理由（イメージ内のベクトルストアが空/古い、RAG_RETRIEVAL_K、キーワード一致の前提）を RAG_ペット・ガス該当なし分析.md に整理し、起動ログの deal 件数や reindex→ビルドの手順で再現・対処できるようにした。
- **運用ドキュメントの整備**: LOCAL_VS_CLOUDRUN、LINE_TROUBLESHOOTING、RAG_ペット・ガス該当なし分析 の役割を分け、README や AGENTS から参照を入れた。再開時や他メンバーが原因調査しやすい。

---

## 3. 課題点

- **ペット・ガス・給湯器で該当なし／返信なしが多発**: ローカルでは期待どおり返るが、Cloud Run では「該当する情報が見つかりません」や返信が来ない事象が続いた。主因は (1) イメージに reindex 済みの data/vector_store が入っていない or 古い、(2) 過去には CSV_SCORE_THRESHOLD・RAG_RETRIEVAL_K がローカルと異なっていたこと。設定はコードで統一したが、**「reindex を忘れずに実行したうえでビルドする」運用が徹底されていないと再発する**。
- **初回レスポンスの遅延と reply token 失効**: Cold Start 時に 15〜30 秒かかると、LINE の reply token（約 30 秒）が切れて返信できない。対策は「2回送る」または min-instances=1（コスト増）であり、根本解にはなっていない。
- **ログの多さ**: Cloud Run のログが多く、手作業で「Vector store initialized」「keyword match」「Reply API success」を追いにくい。フィルタや gcloud logging read の例を案内したが、**構造化ログやログレベルでの絞り込みは未実装**。
- **line-worker 未デプロイ**: Slack 通知経路（Webhook → Pub/Sub → Worker → Slack）は設計・コード上はあるが、line-worker は一度もデプロイされていない。Slack 通知が必要な場合は再開後に Worker と Pub/Sub の構築が必要。
- **gcloud CLI 周り**: ローカル環境の gcloud が Python 3.9 ベースで、非推奨警告や importlib.metadata エラーが出ることがある。Cloud Run の挙動には直接影響しないが、デプロイ作業のノイズになっている。
- **デプロイ失敗の履歴**: 過去に「PORT は予約済みのため設定不可」「コンテナがポートを listen する前にタイムアウト」などのエラーがあり、Dockerfile の CMD や Cloud Run の予約環境変数への対応で解決したが、**初回デプロイ時の試行錯誤が文書化されきっていない**。

---

## 4. 修正を試みたが完全には解決しなかった点

- **ペット・ガスの該当なし**: 設定の統一と分析ドキュメントにより「原因の切り分け方法」と「reindex → ビルド → デプロイ」の手順は明確にした。ただし、**最後に line-webhook を削除した時点で、その手順を踏んだうえで LINE 上でペット・ガスが安定して返ることを検証しきれていない**。再デプロイ後にログで deal=13 と keyword match を確認し、実際に LINE で返信されるかを再度検証する必要がある。
- **レスポンス遅延**: Cold Start と RAG 初期化の時間を説明し、「2回送る」で緩和する旨を LINE_TROUBLESHOOTING に書いた。min-instances=1 はコストのため採用していない。**遅延を許容するか、コストをかけて常時 Warm にするかの判断は未確定**。
- **ログ確認の効率化**: Cloud Logging のフィルタや gcloud logging read の例を案内したが、**スクリプト化やダッシュボード化は行っていない**。再開後にログ検索をスクリプト化するか、重要なメッセージだけを構造化して出すかを検討する価値がある。

---

## 5. 次回以降のプロジェクトへのフィードバック

- **デプロイ前に reindex を必須化する**: Dockerfile 内で reindex を実行するか、CI で「reindex → ビルド」を一括実行するなど、**人間が忘れない仕組み**にすると、Cloud Run でベクトルストアが空になる事象を減らせる。
- **ローカル＝クラウドを最初から設計に組み込む**: 新規でクラウドデプロイするプロジェクトでは、最初から「コードの既定値＝ローカルで使う値」とし、env.example と config のデフォルトを同期する。後から差分を埋めるより、運用ミスが少ない。
- **LINE のような短い token 有効期限を前提にした設計**: reply token が 30 秒で切れるため、非同期で返信する構成は Cold Start と相性が悪い。**同期的に RAG + 返信まで完了させる**現在の設計は妥当。Worker で返信する完全非同期は min-instances=1 や Push API など別の検討が必要。
- **ログは「検索できる前提」で設計する**: 本番に近い環境ではログ量が増えるため、重要なイベント（受信・キーワード一致・返信成功/失敗・ベクトルストア件数）は**固定の文言や構造化フィールド**にし、Cloud Logging の検索やアラートに使いやすくする。
- **デプロイとシャットダウンの手順を両方書く**: デプロイ手順は README や deploy/README にあるが、**コスト削減のためのサービス削除手順**（例: gcloud run services delete）も 1 箇所にまとめておくと、PoC 終了時や再開前の整理がしやすい。

---

## 6. 再開時に着手すべき点（クリティカル評価）

| 優先度 | 内容 | 理由 |
|--------|------|------|
| **必須** | line-webhook の再デプロイとペット・ガスの動作検証 | 現在サービスは削除済み。再度 reindex → ビルド → デプロイ を実行し、Cloud Run ログで「Vector store initialized: deal=13」と「CSV keyword match detected」を確認したうえで、LINE で「ペット」「ガス」を送り、期待どおり返ることを確認する。これができていないと PoC のゴールを満たしたと言い切れない。 |
| **必須** | デプロイ手順の「reindex 必須」の明示と実行チェック | deploy_webhook.sh では data/vector_store の存在チェックはあるが、**中身が直近の reindex で作られたものか**は見ていない。README やスクリプトのコメントで「必ず reindex を実行してからビルドすること」を強調し、可能なら reindex の最終実行時刻を data/ に書き出してビルド時に表示するなど、忘れ防止を強化する。 |
| 推奨 | line-worker + Pub/Sub の構築（Slack 通知が必要な場合） | 設計上 Slack に通知を送るには Worker と Pub/Sub の設定が必要。Slack が必要なら deploy_worker.sh と setup_pubsub.sh を実行し、環境変数（SLACK_WEBHOOK_URL 等）を設定する。 |
| 推奨 | ログの絞り込み・検索の簡便化 | Cloud Logging の保存済みフィルタや、gcloud logging read をラップしたスクリプト（例: 「直近の line-webhook の Vector store initialized と Reply API のログだけ取得」）を用意すると、再発時の確認が速い。 |
| 任意 | Cold Start 対策の判断 | min-instances=0 のまま「2回送る」で許容するか、min-instances=1 でコストをかけて初回から返信を安定させるか、要件と予算で決める。 |
| 任意 | Beads の P1 タスク | 検索精度改善（Recall@5）、ハルシネーション率改善は RAG 品質の向上に直結するが、LINE PoC の「返信できること」が先であれば、再デプロイとペット・ガス検証の後に回す。 |

---

## 7. 関連ドキュメント

- **デプロイ・設定**: README.md（GCP デプロイ）、deploy/README.md、docs/LOCAL_VS_CLOUDRUN.md
- **LINE 運用・障害**: docs/LINE_TROUBLESHOOTING.md
- **該当なしの分析**: docs/RAG_ペット・ガス該当なし分析.md
- **ルール**: AGENTS.md「ローカル＝クラウドのデプロイルール」、.cursor/rules/local-equals-cloud.mdc

---

*本文書は 2026 年 3 月時点の実装と検証状況に基づく。再開時は上記「再開時に着手すべき点」を参照し、必須項目から順に進めることを推奨する。*
