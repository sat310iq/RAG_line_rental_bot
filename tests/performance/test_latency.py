"""Latency tests for KB fast path and hot path p95.

Targets (from kanban TASK-002):
  KB fast path single call : < 100 ms
  Hot path p95 (50 samples): < 500 ms

These tests exercise only pure keyword scoring — no LLM / network calls.
"""

from __future__ import annotations

import os
import time
from typing import List

import pytest

from src.config import load_config, reset_config
from src.kb_fast_path import try_kb_fast_path
from src.kb_loader import load_kb_csv

# ── thresholds ──────────────────────────────────────────────────────────────
KB_FASTPATH_LIMIT_MS: float = 100.0
HOT_PATH_P95_LIMIT_MS: float = 500.0

# ── query corpus ─────────────────────────────────────────────────────────────
_QUERIES: List[str] = [
    "ガス料金を知りたいのですが",
    "水漏れが発生しています",
    "喫煙は可能ですか",
    "鍵をなくしました",
    "エアコンが動きません",
    "退去の手続きを教えてください",
    "敷金は戻ってきますか",
    "騒音がひどいのですが",
    "修繕をお願いしたい",
    "駐車場を借りたい",
]

_WARM_RUNS = 5
_MEASURE_RUNS = 50


@pytest.fixture(scope="module")
def cfg():
    reset_config()
    os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "sk-test-dummy"))
    return load_config(force_reload=True)


@pytest.fixture(scope="module")
def kb_docs(cfg):
    return load_kb_csv(cfg)


def test_kb_fastpath_latency(cfg, kb_docs):
    """KB fast path single call must complete within 100 ms (pure keyword scoring, no LLM)."""
    for _ in range(_WARM_RUNS):
        try_kb_fast_path("ガス", cfg, kb_docs)

    t0 = time.perf_counter()
    try_kb_fast_path("ガス料金を知りたいのですが", cfg, kb_docs)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < KB_FASTPATH_LIMIT_MS, (
        f"KB fast path took {elapsed_ms:.1f} ms — limit is {KB_FASTPATH_LIMIT_MS} ms"
    )


def test_hot_path_p95_latency(cfg, kb_docs):
    """Hot path p95 must be under 500 ms across 50 varied queries (no LLM involved)."""
    queries = (_QUERIES * (_MEASURE_RUNS // len(_QUERIES) + 1))[:_MEASURE_RUNS]
    latencies_ms: List[float] = []

    for q in queries:
        t0 = time.perf_counter()
        try_kb_fast_path(q, cfg, kb_docs)
        latencies_ms.append((time.perf_counter() - t0) * 1000)

    sorted_ms = sorted(latencies_ms)
    p95_idx = int(len(sorted_ms) * 0.95)
    p95 = sorted_ms[p95_idx]
    p50 = sorted_ms[len(sorted_ms) // 2]

    assert p95 < HOT_PATH_P95_LIMIT_MS, (
        f"Hot path p95={p95:.1f} ms exceeds {HOT_PATH_P95_LIMIT_MS} ms limit "
        f"(p50={p50:.1f} ms)"
    )
