"""CLI interface for rental QA chat bot."""

import sys
from typing import Optional

from src.config import load_config
from src.tenant_auth import TenantAuth
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer


def main():
    """Main CLI entry point."""
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        print("Please check your .env file and ensure OPENAI_API_KEY is set.", file=sys.stderr)
        sys.exit(1)
    
    print("=== 賃貸入居者向けQAチャットボット ===")
    print("PoC実装 - 2025標準準拠")
    print()
    
    # Initialize tenant authentication
    tenant_auth = TenantAuth(config)
    tenant_info = None
    tenant_contract_id = None
    
    try:
        # Authenticate user
        print("本人確認を行います。")
        pin = input("PINを入力してください: ").strip()
        
        tenant_info = tenant_auth.authenticate_by_pin(pin)
        if tenant_info is None:
            print("認証に失敗しました。", file=sys.stderr)
            sys.exit(1)
        
        # 認証成功（部屋番号・名前の表示は不要）
        print("認証成功")
        tenant_contract_id = None  # 認証テーブルなしのためNone
    except Exception as e:
        print(f"認証エラー: {e}", file=sys.stderr)
        print("認証をスキップして続行します。", file=sys.stderr)
    
    print()
    print("RAGシステムを初期化しています...")
    
    # Initialize RAG components
    try:
        vector_store_manager = VectorStoreManager(config)
        query_cache = QueryCache(config)
        rag_answerer = RAGAnswerer(
            config,
            vector_store_manager,
            query_cache,
            tenant_auth
        )
        
        # Check collection counts
        counts = vector_store_manager.get_collection_counts()
        total = sum(counts.values())
        if total == 0:
            print("警告: ベクトルストアにデータがありません。")
            print("先に 'python scripts/reindex_vector_db.py' を実行してください。")
            sys.exit(1)
        
        print(f"データベース準備完了 (FAQ: {counts.get('faq', 0)}, PDF: {counts.get('pdf', 0)}, OPS: {counts.get('ops', 0)})")
        
    except Exception as e:
        print(f"RAGシステムの初期化に失敗しました: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print()
    print("質問を入力してください。終了するには 'exit' または 'quit' と入力してください。")
    print("特殊コマンド: '/health' - システム状態確認, '/clear' - キャッシュクリア")
    print()
    
    # REPL loop
    while True:
        try:
            question = input("\n質問: ").strip()
            if not question:
                continue
            
            if question.lower() in ("exit", "quit", "q"):
                print("終了します。")
                break
            
            # Handle special commands
            if question == "/health":
                counts = vector_store_manager.get_collection_counts()
                cache_size = query_cache.size()
                print(f"システム状態:")
                print(f"  - データベース: FAQ={counts.get('faq', 0)}, PDF={counts.get('pdf', 0)}, OPS={counts.get('ops', 0)}")
                print(f"  - キャッシュ: {cache_size}件")
                continue
            
            if question == "/clear":
                query_cache.clear()
                print("キャッシュをクリアしました。")
                continue
            
            # Clear cache for pet-related questions to test
            if "ペット" in question or "pet" in question.lower():
                query_cache.clear()
            
            # Process question through RAG pipeline
            print("検索中...")
            try:
                answer = rag_answerer.answer(question, tenant_contract_id)
                
                # Display structured answer
                print("\n" + "="*60)
                print("【結論】")
                print(answer.conclusion)
                print()
                print("【根拠】")
                for evidence in answer.evidence:
                    print(f"  - {evidence}")
                print()
                print("【次アクション】")
                print(answer.next_action)
                print()
                if answer.caveats:
                    print("【注意点】")
                    print(answer.caveats)
                print("="*60)
                
            except Exception as e:
                print(f"エラー: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
            
        except KeyboardInterrupt:
            print("\n\n終了します。")
            break
        except Exception as e:
            print(f"エラーが発生しました: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
