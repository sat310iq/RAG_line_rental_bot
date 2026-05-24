"""Configuration management with environment variable loading and validation."""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 質問用語同義: RAG relevance guard / has_content_keyword_hit の既定。環境で JSON 上書き可。
# 極小セット（浸水系・抵当権系）のみ; 拡大は eval の rag_relevance_guard を見てから足す。
QUESTION_TERM_SYNONYMS_RAG_DEFAULT: Dict[str, List[str]] = {
    "浸水": ["水害", "洪水"],
    "抵当権": ["差押", "差押さえ", "競売"],
    "使用目的": ["居住", "居住のみ", "居住のみを目的として"],
    "居住": ["使用目的", "住居用途", "住居として"],
    "短期解約": ["短期解約違約金", "解約違約金", "途中解約", "特約④"],
    "違約金": ["短期解約違約金", "解約違約金", "特約④"],
    "解約": ["短期解約", "途中解約", "中途解約"],
}


class Config(BaseSettings):
    """Application settings loaded from environment (Cloud Run + local .env via load_dotenv)."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str = Field(..., description="OpenAI API key")

    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model",
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI chat model (keep same as env.example for local=cloud)",
    )

    rag_vector_store_path: str = Field(
        default="data/vector_store",
        description="Path to ChromaDB persistent directory",
    )
    rag_retrieval_k: int = Field(
        default=16,
        description="Documents to retrieve per source (hybrid top-k; 16 covers ~13 FAQ rows + margin vs local/cloud drift)",
    )
    rag_rerank_candidates: int = Field(default=20, description="Rerank candidates")
    rag_rerank_top_n: int = Field(
        default=5,
        description="Top documents after rerank (slightly wider head for master TXT+KB merge)",
    )
    rag_search_timeout_sec: float = Field(default=10.0, description="Per-collection search timeout (sec). 3 s was too tight on warm Cloud Run with 2 GiB; 10 s gives headroom while staying well within 60 s Cloud Run timeout.")
    csv_score_threshold: float = Field(
        default=0.40,
        description="CSV match threshold; keep aligned with LOCAL_VS_CLOUDRUN.md",
    )
    pdf_score_threshold: float = Field(
        default=0.58,
        description="Master TXT chunk score threshold (legacy env name pdf_score_threshold; same pipeline)",
    )
    pdf_empty_retry_score_threshold: float = Field(
        default=0.52,
        ge=0.0,
        le=1.0,
        description="Master TXT threshold used only on KB-empty master retry (answer() second-stage search).",
    )
    contract_source_pdf_retry_threshold: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Relaxed master TXT score threshold for contract-source retry when initial master is empty.",
    )
    contract_source_master_top_k: int = Field(
        default=12,
        ge=1,
        description="Master top-k used on contract-source path before final rerank truncation.",
    )
    contract_source_retry_top_k: int = Field(
        default=16,
        ge=1,
        description="Top-k used inside contract-source master retry semantic rerank.",
    )
    contract_source_retry_filter_enabled: bool = Field(
        default=True,
        description="If True, apply lightweight pre-merge filter to contract-source retry candidates.",
    )
    contract_source_retry_min_keep: int = Field(
        default=8,
        ge=1,
        description="Minimum number of retry candidates to keep after lightweight filtering.",
    )
    master_section_inject_enabled: bool = Field(
        default=True,
        description=(
            "If True, inject important_matters section chunk by metadata fetch "
            "when G1-G6 conditions are met (PR-1b). Set to false to disable without redeploy."
        ),
    )
    graph_rag_enabled: bool = Field(
        default=False,
        description=(
            "GRAPHRAG-POC-01: If True, expand retrieval pool with 1-hop sidecar_graph edges "
            "after hierarchical search. Set GRAPH_RAG_ENABLED=1 to enable."
        ),
    )
    graph_rag_sidecar_path: str = Field(
        default="data/sidecar_graph.yaml",
        description="Path to sidecar_graph.yaml relative to project root.",
    )
    kb_empty_try_master_pdf: bool = Field(
        default=True,
        description="If True and KB path had no deal+master hits, retry hierarchical search with master TXT enabled.",
    )
    fallback_decision_path: str = Field(
        default="fallback",
        description="decision_path attached when returning fallback_message after retrieval misses.",
    )
    enable_individual_contract_handoff: bool = Field(
        default=True,
        description=(
            "If True, questions that look like tenant-specific terms (without clause citation) "
            "return a short handoff instead of RAG."
        ),
    )
    rag_template_clause_scope_enabled: bool = Field(
        default=True,
        description="If True, prompts emphasize template/clause scope (no individual deal determination).",
    )
    rag_contract_source_drop_kb_faq_entirely: bool = Field(
        default=True,
        description=(
            "If True, contract-source RAG never uses kb_faq chunks as evidence (not only when master TXT exists)."
        ),
    )
    csv_keyword_override_min_hits: int = Field(
        default=2,
        ge=1,
        description="Minimum keyword+keywords_primary token hits for CSV keyword override (unless fusion floor met).",
    )
    csv_keyword_override_min_fusion_score: float = Field(
        default=0.36,
        ge=0.0,
        le=1.0,
        description="If override token hits are below min_hits but fusion score (post negative penalty) meets this, allow override.",
    )
    csv_keyword_override_use_primary: bool = Field(
        default=True,
        description="If True, include keywords_primary in CSV keyword override hit count (aligned with kb_fast_path signals).",
    )
    responder_kb_alignment_enabled: bool = Field(
        default=True,
        description="If True, responder applies question–KB-metadata alignment gate for kb_faq top doc.",
    )
    responder_kb_min_keyword_hits: int = Field(
        default=1,
        ge=1,
        description="Min pipe-field keyword hits vs question for alignment when query is not 'short' (see kb_fast_path_short_max_len).",
    )
    responder_misalignment_fallback_message: str = Field(
        default="該当が不十分なため、詳細は管理会社にお問い合わせください。",
        description="Plain text when responder rejects weak KB–question alignment.",
    )

    pdf_documents_dir: str = Field(
        default="data/documents",
        description="Master TXT sources directory (legacy env name pdf_documents_dir)",
    )
    master_txt_files: str = Field(
        default="グランマーレ大分空港契約書.txt,重要事項説明書.txt",
        description="Comma-separated TXT master basenames (not JSON — avoids pydantic-settings list decode)",
    )
    faq_csv_path: str = Field(
        default="data/faq_kb.csv",
        description="Legacy fallback FAQ CSV (used only when KB loader fails)",
    )
    kb_csv_path: str = Field(default="data/faq_kb.csv", description="KB CSV (15-col)")
    tenant_master_csv: str = Field(default="data/tenants.csv", description="Tenant master CSV")
    fallback_message: str = Field(
        default="該当する情報が見つからないため管理会社にお問い合わせください。",
        description="Fallback message",
    )
    question_term_stopwords: List[str] = Field(default_factory=list)
    question_term_synonyms: Dict[str, List[str]] = Field(
        default_factory=lambda: copy.deepcopy(QUESTION_TERM_SYNONYMS_RAG_DEFAULT),
        description="Head term -> synonyms for question-term extraction and relevance matching (env JSON override).",
    )

    force_reindex_rental_qa: bool = Field(default=False)
    enable_query_cache: bool = Field(default=True)
    cache_ttl_sec: int = Field(default=3600)
    cache_exact_ttl_sec: int = Field(
        default=3600,
        description="TTL for exact cache hits",
    )
    cache_semantic_ttl_sec: int = Field(
        default=1800,
        description="TTL for semantic cache entries",
    )
    cache_semantic_threshold: float = Field(
        default=0.85,
        description="Cosine similarity threshold for semantic cache reuse",
    )

    comet_api_key: Optional[str] = Field(default=None)
    comet_project_name: str = Field(default="rental-rag-poc")
    comet_workspace: Optional[str] = Field(default=None)
    enable_comet_logging: bool = Field(default=False)
    enable_chat_opik_logging: bool = Field(default=True)

    rag_official_contact_patterns: str = Field(
        default="",
        description="Comma-separated extra regex patterns for published/allowed contacts (PII allowlist)",
    )
    semantic_neighbor_classes_path: str = Field(
        default="data/eval/semantic_neighbor_classes.yaml",
        description="YAML: optional neighbor classes for semantic_match (week 2+); optional",
    )

    enable_debug_rag_endpoint: bool = Field(
        default=False,
        description="If True, POST /debug/rag accepts JSON {question} for container smoke (dev only).",
    )

    rag_skip_startup_checks: bool = Field(
        default=False,
        description=(
            "Env: RAG_SKIP_STARTUP_CHECKS. If True, skip run_startup_checks in FastAPI lifespan "
            "(Cloud Run smoke / dummy key). Use GET /ready for full RAG dependency checks."
        ),
    )

    kb_fast_path_enabled: bool = Field(
        default=True,
        description="If False, KB fast path is skipped (all queries go to RAG).",
    )
    kb_fast_path_score_threshold: int = Field(
        default=4,
        description=(
            "Minimum fast-path score to allow KB instant answer (primary 3, sec/syn 1, exclude 5; "
            "primary exact-match +3). Primary+secondary alone can reach 4—tune to 5–6 if false hits "
            "appear; monitor kb_fast_path_hit vs manual review."
        ),
        ge=1,
    )
    kb_fast_path_ambiguity_delta: int = Field(
        default=2,
        description="If top two intent scores differ by less than this, return clarification instead (tighter = more clar when top-2 are close).",
        ge=0,
    )
    kb_fast_path_short_max_len: int = Field(
        default=10,
        description=(
            "Normalized query length (chars) at or below = 'short' for needs_clarification_when_short. "
            "12 was too high: e.g. 「ガス給湯器のお湯が出ない」(12) must answer, not loop on clarification."
        ),
        ge=1,
    )
    kb_fast_path_short_bypass_score: int = Field(
        default=7,
        description=(
            "With query length >= kb_fast_path_short_bypass_min_len, treat as specific enough to skip "
            "short clarification when top_score meets this (e.g. 「ガス」 stays clar; 「お湯が出ない」 hits)."
        ),
        ge=1,
    )
    kb_fast_path_short_bypass_min_len: int = Field(
        default=4,
        description=(
            "Min normalized query length for short-bypass (score/multi-hit/exact-bonus arms). "
            "Keeps 「ガス」 in clarification; 「証明書」 alone does not bypass on exact bonus only."
        ),
        ge=1,
    )
    kb_fast_path_legal_skip_substrings: str = Field(
        default="違法,訴え,裁判,弁護士,窃盗,訴状,減額請求,市場相場,刑事,民事",
        description="Comma-separated substrings; if any appear in question, fast path is skipped.",
    )

    @field_validator("master_txt_files", mode="before")
    @classmethod
    def _parse_master_txt(cls, v: object) -> object:
        if v is None or v == "":
            return "グランマーレ大分空港契約書.txt,重要事項説明書.txt"
        if isinstance(v, list):
            return ",".join(str(item).strip() for item in v if str(item).strip())
        return v

    @field_validator("question_term_stopwords", mode="before")
    @classmethod
    def _parse_stopwords(cls, v: object) -> object:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("question_term_synonyms", mode="before")
    @classmethod
    def _parse_synonyms(cls, v: object) -> object:
        if v is None or v == "":
            return {}
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v

    @field_validator("comet_api_key", "comet_workspace", mode="before")
    @classmethod
    def _empty_optional_str(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @field_validator("openai_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not v or v == "your_openai_api_key_here":
            raise ValueError("OPENAI_API_KEY must be set in environment or .env file")
        return v

    @field_validator("rag_retrieval_k", "rag_rerank_candidates", "rag_rerank_top_n")
    @classmethod
    def validate_positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"Value must be positive, got {v}")
        return v

    @field_validator("rag_search_timeout_sec")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Timeout must be positive, got {v}")
        return v

    def get_vector_store_path(self) -> Path:
        return Path(self.rag_vector_store_path)

    def get_source_score_thresholds(self) -> Dict[str, float]:
        return {"csv": self.csv_score_threshold, "pdf": self.pdf_score_threshold}

    def get_pdf_documents_dir(self) -> Path:
        return Path(self.pdf_documents_dir)

    def get_master_txt_files(self) -> List[str]:
        # Cloud Run / shell often pass multiple basenames with ";" to avoid gcloud comma-escaping.
        raw = (self.master_txt_files or "").replace(";", ",")
        return [item.strip() for item in raw.split(",") if item.strip()]

    def get_faq_csv_path(self) -> Path:
        return Path(self.faq_csv_path)

    def get_kb_csv_path(self) -> Path:
        return Path(self.kb_csv_path)

    def get_tenant_master_csv_path(self) -> Path:
        return Path(self.tenant_master_csv)

    def get_expected_id_aliases_path(self) -> Path:
        """Path to eval-only legacy ID -> canonical intent aliases (YAML)."""
        return Path(__file__).resolve().parent.parent / "data" / "eval" / "expected_id_aliases.yaml"

    def get_rag_official_contact_pattern_list(self) -> List[str]:
        return [p.strip() for p in self.rag_official_contact_patterns.split(",") if p.strip()]

    def get_semantic_neighbor_classes_path(self) -> Path:
        p = Path(self.semantic_neighbor_classes_path)
        if not p.is_absolute():
            return Path(__file__).resolve().parent.parent / p
        return p


_config: Optional[Config] = None

_last_env_bootstrap: Dict[str, Any] = {}


def get_env_bootstrap_meta() -> Dict[str, Any]:
    """Snapshot of how dotenv was loaded (for CONFIG_SUMMARY / debugging)."""
    return dict(_last_env_bootstrap)


def bootstrap_dotenv(project_root: Optional[Path] = None) -> None:
    """Load env files in a reproducible order.

    1) If RENTAL_RAG_SHARED_ENV_FILE is set, load that file first (explicit override).
    2) Load the project-local .env (never a sibling-repo path).

    Cloud Run: env vars are injected by the runtime — no .env file is read.
    Local dev: copy env.example to .env and fill in secrets.
    """
    global _last_env_bootstrap

    root = project_root or Path(__file__).resolve().parent.parent
    meta: Dict[str, Any] = {
        "mode": "bootstrap",
        "project_root": str(root.resolve()),
        "shared_env_override_var": None,
        "shared_env_loaded_path": None,
        "rental_env_path": str((root / ".env").resolve()),
        "rental_env_loaded": False,
    }

    shared_override = os.environ.get("RENTAL_RAG_SHARED_ENV_FILE", "").strip()
    if shared_override:
        shared_path = Path(shared_override).expanduser().resolve()
        meta["shared_env_override_var"] = shared_override
        if not shared_path.is_file():
            raise RuntimeError(
                f"RENTAL_RAG_SHARED_ENV_FILE is set but file not found: {shared_path}. "
                "Fix the path or unset the variable."
            )
        load_dotenv(shared_path, override=False)
        meta["shared_env_loaded_path"] = str(shared_path)

    rental_env = root / ".env"
    if rental_env.is_file():
        load_dotenv(rental_env, override=False)
        meta["rental_env_loaded"] = True

    _last_env_bootstrap = meta


def reset_config() -> None:
    """Clear cached config (tests / scripts)."""
    global _config, _last_env_bootstrap
    _config = None
    _last_env_bootstrap = {}


def load_config(env_file: Optional[str] = None, *, force_reload: bool = False) -> Config:
    """Load configuration: dotenv then pydantic Settings from os.environ."""
    global _config

    if _config is not None and not force_reload and env_file is None:
        return _config

    if force_reload or env_file is not None:
        _config = None

    project_root = Path(__file__).resolve().parent.parent
    global _last_env_bootstrap
    if env_file:
        p = Path(env_file).expanduser().resolve()
        load_dotenv(p, override=True)
        _last_env_bootstrap = {
            "mode": "explicit_env_file",
            "path": str(p),
        }
    else:
        bootstrap_dotenv(project_root)

    _config = Config()
    return _config


def get_config() -> Config:
    if _config is None:
        return load_config()
    return _config
