"""Smoke test for RAG system."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.tenant_auth import TenantAuth
from src.vector_store_manager import VectorStoreManager
from src.query_cache import QueryCache
from src.rag_answerer import RAGAnswerer


def check_pii_leakage(text: str) -> bool:
    """Check for PII leakage."""
    import re
    patterns = [
        r'\d{1,4}号室',
        r'0\d{1,4}-\d{1,4}-\d{4}',
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',
    ]
    
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    
    return False


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
        answer = rag_answerer.answer(question, tenant_contract_id)
        
        # Check structured output format
        if not hasattr(answer, 'conclusion'):
            result["errors"].append("Missing 'conclusion' field")
        if not hasattr(answer, 'evidence'):
            result["errors"].append("Missing 'evidence' field")
        if not hasattr(answer, 'next_action'):
            result["errors"].append("Missing 'next_action' field")
        if not hasattr(answer, 'caveats'):
            result["errors"].append("Missing 'caveats' field")
        
        # Check evidence is not empty
        if not answer.evidence:
            result["errors"].append("Evidence list is empty")
        
        # Check PII leakage
        answer_text = f"{answer.conclusion} {answer.next_action} {answer.caveats}"
        if check_pii_leakage(answer_text):
            result["errors"].append("PII leakage detected")
        
        # Check references are present
        if not any('ID' in str(e) or 'id' in str(e).lower() or 'ページ' in str(e) or 'ログ' in str(e) for e in answer.evidence):
            result["warnings"] = ["No clear references found in evidence"]
        
        if not result["errors"]:
            result["passed"] = True
        
        result["answer"] = {
            "conclusion": answer.conclusion[:100] + "..." if len(answer.conclusion) > 100 else answer.conclusion,
            "evidence_count": len(answer.evidence),
            "next_action": answer.next_action[:50] + "..." if len(answer.next_action) > 50 else answer.next_action,
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
        
        print(f"Database ready (FAQ: {counts.get('faq', 0)}, PDF: {counts.get('pdf', 0)}, OPS: {counts.get('ops', 0)})")
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
            print(f"    Conclusion: {result['answer']['conclusion']}")
            print(f"    Evidence count: {result['answer']['evidence_count']}")
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
