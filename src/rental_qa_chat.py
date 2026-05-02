"""CLI interface for rental QA chat bot."""

import sys
import argparse
import os
import uuid
import time
from typing import Optional

from src.config import load_config
from src.tenant_auth import TenantAuth
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer
from src.evaluate import evaluate_question
from src.opik_integration import OpikIntegration


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

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--channel", type=str, default=None)
    args, _ = parser.parse_known_args()
    channel = args.channel or os.getenv("DEFAULT_CHANNEL", "cli")
    
    # Initialize tenant authentication
    tenant_auth = TenantAuth(config)
    tenant_info = None
    tenant_contract_id = None
    
    try:
        # Authenticate user
        print("本人確認を行います。")
        pin = input("PINを入力してください: ").strip()
        room_number = input("部屋番号を入力してください: ").strip()
        tenant_name = input("お名前を入力してください: ").strip()
        
        tenant_info = tenant_auth.authenticate_by_pin(pin)
        if tenant_info is None:
            print("認証に失敗しました。", file=sys.stderr)
            sys.exit(1)
        
        # 認証成功
        print("認証成功")
        print(f"部屋番号: {room_number}, お名前: {tenant_name}")
        
        # セッション情報として保持（PINはセキュリティのため含めない）
        session_info = {
            'room_number': room_number,
            'name': tenant_name
        }
        
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
        if "--reset-cache" in sys.argv:
            query_cache.clear()
            print("起動時オプションによりキャッシュをクリアしました。")
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
        
        print(f"データベース準備完了 (Deal CSV: {counts.get('deal', 0)}, Master PDF: {counts.get('master', 0)})")
        
    except Exception as e:
        print(f"RAGシステムの初期化に失敗しました: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print()
    print("質問を入力してください。終了するには 'exit' または 'quit' と入力してください。")
    print("特殊コマンド: '/health' - システム状態確認, '/clear' or '/clear_cache' - キャッシュクリア")
    print()
    
    # Initialize OPIK integration for chat logging (if enabled)
    opik = None
    session_thread_id = None
    if config.enable_chat_opik_logging:
        try:
            # Force enable OPIK for chat even if enable_comet_logging is False
            opik = OpikIntegration(config, force_enable=True)
            session_thread_id = f"chat_session_{uuid.uuid4().hex[:8]}"
            print(f"OPIKロギングが有効です (セッションID: {session_thread_id})")
        except Exception as e:
            print(f"警告: OPIK統合の初期化に失敗しました: {e}", file=sys.stderr)
            print("OPIKロギングなしで続行します。", file=sys.stderr)
            opik = None
    
    # REPL loop
    question_counter = 0
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
                print(f"  - データベース: Deal CSV={counts.get('deal', 0)}, Master PDF={counts.get('master', 0)}")
                print(f"  - キャッシュ: {cache_size}件")
                continue
            
            if question in ("/clear", "/clear_cache"):
                query_cache.clear()
                print("キャッシュをクリアしました。")
                continue
            
            # Clear cache for pet-related questions to test
            if "ペット" in question or "pet" in question.lower():
                query_cache.clear()
            
            # Process question through RAG pipeline
            print("検索中...")
            try:
                answer = rag_answerer.answer(question, tenant_contract_id, tenant_info=session_info)
                
                # Display structured answer (V2: use render_answer_text)
                from src.rag_answerer import render_answer_text
                is_urgent = "緊急度: high" in (answer.caveats or "")
                print("\n" + "="*60)
                print("【回答】")
                if channel == "line":
                    # LINE: show summary only, hide escalation-related lines
                    summary = (answer.summary or "").strip()
                    lines = [line for line in summary.splitlines() if line.strip()]
                    filtered = []
                    skip_next = False
                    for line in lines:
                        if skip_next:
                            skip_next = False
                            continue
                        if line.startswith("この件は管理会社での対応が必要です。"):
                            skip_next = True
                            continue
                        filtered.append(line)
                    answer_text = "\n".join(filtered).strip()
                    if is_urgent and not answer_text.startswith("【緊急・注意】"):
                        answer_text = f"【緊急・注意】\n{answer_text}"
                else:
                    answer_text = render_answer_text(answer)
                print(answer_text)
                print()
                if channel != "line":
                    print("【根拠】")
                    if answer.items:
                        for idx, item in enumerate(answer.items, 1):
                            citation = f" ({item.citation})" if item.citation else ""
                            print(f"{idx}. {item.text}{citation}")
                    else:
                        for evidence in answer.evidence:
                            print(f"  - {evidence}")
                print("="*60)
                
                # エスカレーションデータがあれば表示
                if channel != "line" and hasattr(answer, 'escalation_data') and answer.escalation_data:
                    import json
                    print("\n" + "="*60)
                    print("【管理会社・オーナー連携用データ】")
                    print(json.dumps(answer.escalation_data, ensure_ascii=False, indent=2))
                    print("="*60)
                
                # Evaluate and log to OPIK (if enabled)
                if opik is not None and config.enable_chat_opik_logging:
                    try:
                        question_counter += 1
                        # Evaluate answer (without expected_doc_ids for chat)
                        result = evaluate_question(
                            question=question,
                            expected_doc_ids=None,  # No expected IDs for interactive chat
                            expected_answer=None,
                            rag_answerer=rag_answerer,
                            llm_model=config.openai_model,
                            tenant_contract_id=tenant_contract_id,
                            pii_extra_allowlist_patterns=config.get_rag_official_contact_pattern_list(),
                            semantic_equivalence=None,
                        )
                        
                        # Generate question_id and add session metadata
                        result["question_id"] = f"CHAT_{int(time.time())}_{question_counter}"
                        result["category"] = "interactive_chat"
                        result["thread_id"] = session_thread_id
                        
                        # Log to OPIK with experiment_type="chat"
                        opik.log_evaluation_result(result, experiment_type="chat")
                    except Exception as e:
                        print(f"警告: OPIKロギングに失敗しました: {e}", file=sys.stderr)
                        import traceback
                        traceback.print_exc()
                
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
    
    # Close OPIK integration at end of session
    if opik is not None:
        try:
            opik.close()
            print("OPIKロギングを終了しました。")
        except Exception as e:
            print(f"警告: OPIK終了処理に失敗しました: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
