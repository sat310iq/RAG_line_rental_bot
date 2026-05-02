# Cloud Run 特有の制約と対策

## ファイルシステム

- **読み取り**: アプリの作業ディレクトリはイメージ内の `/app`。`data/` と `data/vector_store` は**ビルド時に焼き込む**前提（実行時に GCS から同期する構成の場合は別途設計）。
- **書き込み**: コンテナのルートは基本的に読み取り専用。**永続書き込みは `/tmp`** のみを想定（キャッシュや一時ファイル）。長期 state は DB / GCS 等に逃がす。

## 環境変数

- ローカルの `.env` は本番にコピーされない。Cloud Run の「変数とシークレット」で設定する。
- `CSV_SCORE_THRESHOLD` / `RAG_RETRIEVAL_K` 等は [LOCAL_VS_CLOUDRUN.md](LOCAL_VS_CLOUDRUN.md) と **env.example** に合わせること。

## ネットワーク・起動

- **PORT**: Cloud Run が注入する `PORT`（通常 8080）で listen する。
- **Cold start**: 初回リクエストが遅延しうる。`/health` と `/ready` でプロセスと RAG 準備を分離して監視する。
- **メモリ / CPU / タイムアウト**: RAG + Chroma + LLM はメモリを使う。必要に応じて Cloud Run の上限とクライアント側タイムアウトを調整する。

## パス解決

- **相対パス**は cwd が `/app` であることを前提にする。`Path.cwd()` 基準で `data/vector_store` を解決する実装と整合させる。
- ローカルと本番で cwd を揃える（Dockerfile の `WORKDIR /app`）。

## 起動時検証

- **manifest** と **KB の SHA256** を起動時に検証し、ベイク済み index と KB の食い違いを早期に検知する。
- 詳細は `startup_check` と `preflight_check.py` を参照。
