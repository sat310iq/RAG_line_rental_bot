"""Document identification helpers."""

from langchain_core.documents import Document


def doc_key(doc: Document) -> str:
    """Build a stable key for deduplication."""
    intent = doc.metadata.get("intent")
    if intent:
        return f"intent:{intent}"
    filename = doc.metadata.get("filename")
    page = doc.metadata.get("page")
    if filename and page is not None:
        article = doc.metadata.get("article_number")
        if article:
            return f"file:{filename}:{article}:p{page}"
        return f"file:{filename}:p{page}"
    return f"hash:{hash(doc.page_content)}"
