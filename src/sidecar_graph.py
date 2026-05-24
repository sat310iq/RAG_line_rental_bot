"""GraphRAG sidecar graph — 1-hop chunk expansion from hand-crafted edge definitions.

GRAPHRAG-POC-01: sidecar_graph.yaml を読み込み、retrieval 済み docs を起点に
隣接ノードを fetch して pool に追加する。LLM entity 抽出なし、Vector 検索なし。

Usage:
    graph = SidecarGraph.load(yaml_path, vsm)
    extra_docs = graph.expand(retrieved_docs)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import yaml
from langchain_core.documents import Document

if TYPE_CHECKING:
    from src.vector_store_manager import VectorStoreManager

logger = logging.getLogger(__name__)

_LIMIT_PER_EDGE = 5  # max docs fetched per matched edge


def _doc_key(doc: Document) -> Any:
    return (doc.metadata or {}).get("stable_id") or hash(doc.page_content)


def _matches_spec(meta: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    for k, v in spec.items():
        if k == "cite_label_contains":
            if v not in (meta.get("cite_label") or ""):
                return False
        elif k == "section_id":
            if str(meta.get("section_id") or "") != str(v):
                return False
        else:
            if meta.get(k) != v:
                return False
    return True


def _fetch_by_spec(spec: Dict[str, Any], vsm: "VectorStoreManager") -> List[Document]:
    """Fetch chunks from master_vector_store matching a 'to' spec."""
    if not vsm.master_vector_store:
        return []

    # Build Chroma WHERE from exact-match keys only
    where_clauses = []
    for k, v in spec.items():
        if k == "cite_label_contains":
            continue  # filtered in Python below
        where_clauses.append({k: {"$eq": v}})

    where: Optional[Dict] = None
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    try:
        result = vsm.master_vector_store._collection.get(
            where=where,
            limit=_LIMIT_PER_EDGE * 3,  # over-fetch then filter
        )
    except Exception:
        logger.exception("sidecar_graph fetch failed spec=%s", spec)
        return []

    docs: List[Document] = []
    label_filter: Optional[str] = spec.get("cite_label_contains")
    for content, meta in zip(
        result.get("documents") or [],
        result.get("metadatas") or [],
    ):
        if content is None:
            continue
        if label_filter and label_filter not in (meta.get("cite_label") or ""):
            continue
        docs.append(Document(page_content=content, metadata=meta or {}))
        if len(docs) >= _LIMIT_PER_EDGE:
            break
    return docs


class SidecarGraph:
    def __init__(self, edges: List[Dict[str, Any]], vsm: "VectorStoreManager") -> None:
        self._edges = edges
        self._vsm = vsm

    @classmethod
    def load(cls, yaml_path: str, vsm: "VectorStoreManager") -> "SidecarGraph":
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        edges = data.get("edges") or []
        logger.info("sidecar_graph loaded edges=%d from %s", len(edges), yaml_path)
        return cls(edges, vsm)

    def expand(self, docs: List[Document]) -> List[Document]:
        """Return additional docs reachable in 1 hop from any doc in `docs`.

        Deduplicates against `docs` and across fetched results.
        """
        if not docs or not self._edges:
            return []

        seen = {_doc_key(d) for d in docs}
        expanded: List[Document] = []
        matched_rels: List[str] = []

        for doc in docs:
            meta = doc.metadata or {}
            for edge in self._edges:
                from_spec = edge.get("from", {})
                to_spec = edge.get("to", {})
                rel = edge.get("rel", "")
                if not _matches_spec(meta, from_spec):
                    continue
                fetched = _fetch_by_spec(to_spec, self._vsm)
                for fd in fetched:
                    key = _doc_key(fd)
                    if key not in seen:
                        seen.add(key)
                        expanded.append(fd)
                        if rel not in matched_rels:
                            matched_rels.append(rel)

        if expanded:
            logger.info(
                "sidecar_graph expand: added=%d rels=%s",
                len(expanded),
                matched_rels,
            )
        return expanded
