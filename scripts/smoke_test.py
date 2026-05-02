"""Smoke test for RAG system."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.metrics import analyze_pii
from src.tenant_auth import TenantAuth
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer


def test_question(
    question: str,
    rag_answerer: RAGAnswerer,
    tenant_contract_id: str
) -> dict:
    """Test a single question.
    
    Returns:
        Test result dictionary
    """
    result = {
        "question": question,
        "passed": False,
        "errors": [],
    }
    
    try:
        answer = rag_answerer.answer(question, tenant_contract_id, persist_cache=False)

        # AnswerSchema V2: items, summary, evidence, next_action, caveats
        if not hasattr(answer, "items") or not answer.items:
            result["errors"].append("Missing or empty 'items'")
        if not hasattr(answer, "summary"):
            result["errors"].append("Missing 'summary' field")
        if not hasattr(answer, "evidence"):
            result["errors"].append("Missing 'evidence' field")
        if not hasattr(answer, "next_action"):
            result["errors"].append("Missing 'next_action' field")
        if not hasattr(answer, "caveats"):
            result["errors"].append("Missing 'caveats' field")

        decision_path = getattr(answer, "decision_path", None) or ""
        if not answer.evidence and decision_path not in ("escalation", "fallback", "clarification"):
            result["errors"].append("Evidence list is empty")

        item_texts = " ".join(getattr(i, "text", "") or "" for i in (answer.items or []))
        answer_text = f"{answer.summary} {item_texts} {answer.next_action} {answer.caveats}"
        pii = analyze_pii(
            answer_text,
            rag_answerer.config.get_rag_official_contact_pattern_list(),
        )
        if pii.get("pii_true_leak_suspected"):
            result["errors"].append(
                "PII true leak suspected (e.g. room number or personal email in answer)"
            )

        def _evidence_looks_like_reference(evidence: list) -> bool:
            for e in evidence:
                s = str(e)
                if any(
                    token in s
                    for token in (
                        "ID",
                        "ページ",
                        "ログ",
                        "契約_",
                        "master",
                        "pdf",
                        "stable_id",
                        ".txt",
                        "グランマーレ",
                    )
                ):
                    return True
                if "id" in s.lower():
                    return True
            return False

        if answer.evidence and not _evidence_looks_like_reference(answer.evidence):
            result["warnings"] = ["No clear references found in evidence"]

        if not result["errors"]:
            result["passed"] = True

        summary_preview = answer.summary[:120] + "..." if len(answer.summary) > 120 else answer.summary
        result["answer"] = {
            "summary": summary_preview,
            "evidence_count": len(answer.evidence),
            "next_action": answer.next_action[:50] + "..." if len(answer.next_action) > 50 else answer.next_action,
            "decision_path": decision_path or None,
        }
        
    except Exception as e:
        result["errors"].append(f"Exception: {str(e)}")
        import traceback
        result["traceback"] = traceback.format_exc()
    
    return result


def main():
    """Main smoke test function."""
    print("=== RAG System Smoke Test ===")
    print()
    
    try:
        config = load_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Test questions
    test_questions = [
        "退去時の原状回復の基本方針は？",
        "契約で禁止されている行為は？",
        "水漏れがあった場合の一次対応は？",
    ]
    
    print("Initializing RAG system...")
    
    try:
        tenant_auth = TenantAuth(config)
        tenant_contract_id = "CONTRACT001"  # Use default for smoke test
        
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
            print("ERROR: No data in vector stores.")
            print("Please run 'python scripts/reindex_vector_db.py' first.")
            sys.exit(1)
        
        print(f"Database ready (Deal CSV: {counts.get('deal', 0)}, Master PDF: {counts.get('master', 0)})")
        print()
        
    except Exception as e:
        print(f"ERROR: Failed to initialize RAG system: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Run tests
    print("Running smoke tests...")
    print()
    
    all_passed = True
    for idx, question in enumerate(test_questions, 1):
        print(f"[{idx}/{len(test_questions)}] Testing: {question}")
        result = test_question(question, rag_answerer, tenant_contract_id)
        
        if result["passed"]:
            print("  ✓ PASSED")
            print(f"    Summary: {result['answer']['summary']}")
            print(f"    Evidence count: {result['answer']['evidence_count']}")
            if result["answer"].get("decision_path"):
                print(f"    decision_path: {result['answer']['decision_path']}")
        else:
            print("  ✗ FAILED")
            for error in result["errors"]:
                print(f"    - {error}")
            all_passed = False
        
        if "warnings" in result:
            for warning in result["warnings"]:
                print(f"    ⚠ WARNING: {warning}")
        
        print()
    
    # Summary
    print("=== Test Summary ===")
    if all_passed:
        print("✓ All tests passed!")
        sys.exit(0)
    else:
        print("✗ Some tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
