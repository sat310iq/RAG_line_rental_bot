# テストの優先順位（このプロジェクト向け）

1. **高速・決定的**: ルーター判定、条文抽出、フォーマット（`contract_rag_format` 等）
2. **モック付き RAGAnswerer**: プロンプト選択・evidence 形状
3. **実インデックス smoke**: 変更後のみ・少数クエリ

詳細: [`docs/TESTING_LAYERS.md`](../../../../../docs/TESTING_LAYERS.md)
