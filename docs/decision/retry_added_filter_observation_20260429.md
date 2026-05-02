# retry_added抑制の追加観測メモ（2026-04-29）

## 背景
- 第3条系の再検索強化により正答率は改善したが、`retry_added` が多くノイズ混入・遅延の懸念があった。
- 軽量フィルタ導入後に、性能改善の因果を追加確認した。

## 変更点（観測用）
- `search_debug_info` に以下を追加。
  - `rerank_pool_count`
  - `llm_evidence_char_len`
  - `llm_evidence_token_estimate`（`char_len // 4`）

## before / after（代表5問）
- `retry_filter=False` -> `True` の比較。
- `avg_retry_added`: `17.75 -> 6.00`
- `avg_rerank_pool_count`: `16.2 -> 7.2`
- `avg_llm_evidence_char_len`: `578.4 -> 534.2`
- `avg_latency_ms`: `803.47 -> 643.23`
- 条文ヒット率（条番号あり4問）: 維持（劣化なし）

## 学び
- TopKを触る前に「候補プール制御（retry時の前処理）」を行うと、ノイズ削減とレイテンシ改善を同時に達成しやすい。
- 観測項目を先に増やしておくと、改善の妥当性を定量で説明できる。
