"""Vector store build manifest for reproducibility (eval / deploy traceability)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

MANIFEST_FILENAME = "manifest.json"

# Must match chunking in document_loader / kb paths where applicable
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head_short(project_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()[:12]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


def manifest_path_for_vector_root(vector_store_root: Path) -> Path:
    return vector_store_root / MANIFEST_FILENAME


def write_vector_store_manifest(
    *,
    vector_store_root: Path,
    embedding_model: str,
    kb_csv_path: Path,
    deal_doc_count: int,
    master_doc_count: int,
    git_commit: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    vector_store_root.mkdir(parents=True, exist_ok=True)
    root = project_root or vector_store_root.parent.parent
    kb_hash = sha256_file(kb_csv_path) if kb_csv_path.is_file() else ""
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = git_commit or git_head_short(root)
    data: Dict[str, Any] = {
        "built_at": built_at,
        "git_commit": commit,
        "embedding_model": embedding_model,
        "chunk_size": DEFAULT_CHUNK_SIZE,
        "chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "kb_csv_path": str(kb_csv_path.as_posix()),
        "kb_sha256": kb_hash,
        "deal_doc_count": deal_doc_count,
        "master_doc_count": master_doc_count,
        "total_indexed_docs": deal_doc_count + master_doc_count,
    }
    out = manifest_path_for_vector_root(vector_store_root)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def load_vector_store_manifest(vector_store_root: Path) -> Optional[Dict[str, Any]]:
    path = manifest_path_for_vector_root(vector_store_root)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
