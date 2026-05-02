#!/usr/bin/env python3
"""Preflight checks before Docker build / deploy: KB vs manifest, required paths."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    root = _root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from src.config import bootstrap_dotenv, get_env_bootstrap_meta

    parser = argparse.ArgumentParser(description="Pre-deploy preflight checks")
    parser.add_argument(
        "--skip-kb-hash",
        action="store_true",
        help="Do not require KB SHA256 to match manifest (emergency only)",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="After success, print public_config_snapshot JSON (needs OPENAI_API_KEY; compare with Cloud CONFIG_SUMMARY / GET /debug/config)",
    )
    args = parser.parse_args()

    bootstrap_dotenv(root)
    print("env_bootstrap:", json.dumps(get_env_bootstrap_meta(), ensure_ascii=False))
    # Explicit path: document primary env var (Chroma persistent dir)
    vs_rel = os.getenv("RAG_VECTOR_STORE_PATH", "data/vector_store")
    print(f"RAG_VECTOR_STORE_PATH (resolved check): {vs_rel}")
    kb_rel = os.getenv("KB_CSV_PATH", "data/faq_kb.csv")
    vs = root / vs_rel
    kb = root / kb_rel
    manifest_path = vs / "manifest.json"

    errors: list[str] = []

    if not vs.is_dir():
        errors.append(f"vector store directory missing: {vs}")
    if not manifest_path.is_file():
        errors.append(f"manifest missing (run reindex): {manifest_path}")
    else:
        try:
            with open(manifest_path, "r", encoding="utf-8") as mf:
                manifest_preview = json.load(mf)
            keys = ("built_at", "git_commit", "kb_sha256", "total_indexed_docs", "deal_doc_count", "master_doc_count")
            snap = {k: manifest_preview.get(k) for k in keys if k in manifest_preview}
            if snap:
                print("manifest (subset):", json.dumps(snap, ensure_ascii=False))
        except Exception as e:
            errors.append(f"manifest read failed: {e}")
    if not kb.is_file():
        errors.append(f"KB CSV missing: {kb}")

    for rel in (
        "bm25_corpora/kb_deal_csv.jsonl",
        "bm25_corpora/kb_master_pdf.jsonl",
    ):
        p = vs / rel
        if not p.is_file() or p.stat().st_size == 0:
            errors.append(f"BM25 corpus missing or empty: {p}")

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(vs.resolve()))
        names = {c.name for c in client.list_collections()}
        for need in ("kb_deal_csv", "kb_master_pdf"):
            if need not in names:
                errors.append(f"Chroma collection missing: {need} (have {sorted(names)})")
            else:
                coll = client.get_collection(need)
                cnt = coll.count()
                if cnt <= 0:
                    errors.append(f"Chroma collection empty (count={cnt}): {need}")
                else:
                    print(f"Chroma OK: {need} count={cnt}")
    except Exception as e:
        errors.append(f"Chroma collection check failed: {e}")

    for rel in ("deploy/Dockerfile.webhook", "deploy/cloudbuild_webhook.yaml"):
        if not (root / rel).is_file():
            errors.append(f"Deploy artifact missing: {root / rel}")

    if errors:
        print("PREFLIGHT FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if not args.skip_kb_hash:
        from src.vector_store_manifest import sha256_file

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        expected = manifest.get("kb_sha256") or ""
        if not expected:
            print("PREFLIGHT FAILED: manifest has no kb_sha256", file=sys.stderr)
            return 1
        current = sha256_file(kb)
        if current != expected:
            print(
                f"PREFLIGHT FAILED: KB hash mismatch. Re-run reindex.\n"
                f"  manifest: {expected[:24]}...\n"
                f"  current:  {current[:24]}...\n"
                f"  kb file:  {kb}",
                file=sys.stderr,
            )
            return 1

    print("PREFLIGHT OK: vector store, manifest, KB hash, and deploy files look good.")
    print("STEP1_DATA_OK: deal collection populated (see Chroma OK lines above). Safe to docker build.")

    if args.print_config:
        try:
            from src.config import load_config
            from src.config_summary import public_config_snapshot

            cfg = load_config()
            snap = public_config_snapshot(cfg)
            print(
                "CONFIG_SNAPSHOT (local; compare with Cloud logs CONFIG_SUMMARY or GET /debug/config):",
                json.dumps(snap, ensure_ascii=False),
            )
        except Exception as e:
            print(f"CONFIG_SNAPSHOT skipped: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
