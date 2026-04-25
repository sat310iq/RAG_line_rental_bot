"""Configuration management with environment variable loading and validation."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
        default=4,
        description="Top documents after rerank (slightly wider head for PDF+KB merge)",
    )
    rag_search_timeout_sec: float = Field(default=3.0, description="Search timeout seconds")
    csv_score_threshold: float = Field(
        default=0.40,
        description="CSV match threshold; keep aligned with LOCAL_VS_CLOUDRUN.md",
    )
    pdf_score_threshold: float = Field(
        default=0.58,
        description="PDF match threshold (slightly relaxed vs 0.60 for recall; override path guarded elsewhere)",
    )
    pdf_empty_retry_score_threshold: float = Field(
        default=0.52,
        ge=0.0,
        le=1.0,
        description="PDF threshold used only on KB-empty master retry (answer() second-stage search).",
    )
    kb_empty_try_master_pdf: bool = Field(
        default=True,
        description="If True and KB path had no deal+master hits, retry hierarchical search with master PDF enabled.",
    )
    fallback_decision_path: str = Field(
        default="fallback",
        description="decision_path attached when returning fallback_message after retrieval misses.",
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

    pdf_documents_dir: str = Field(default="data/documents", description="PDF/TXT documents dir")
    master_txt_files: str = Field(
        default="グランマーレ大分空港契約書.txt",
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
    question_term_synonyms: Dict[str, List[str]] = Field(default_factory=dict)

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
            return "グランマーレ大分空港契約書.txt"
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
        return [item.strip() for item in self.master_txt_files.split(",") if item.strip()]

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

# Shared secrets file (sibling assignment repo layout). Override with RENTAL_RAG_SHARED_ENV_FILE.
_SHARED_ENV_RELATIVE = Path("..") / "LangGraph" / "code" / ".env"

_last_env_bootstrap: Dict[str, Any] = {}
_implicit_shared_warned: bool = False


def get_env_bootstrap_meta() -> Dict[str, Any]:
    """Snapshot of how dotenv was loaded (for CONFIG_SUMMARY / debugging)."""
    return dict(_last_env_bootstrap)


def bootstrap_dotenv(project_root: Optional[Path] = None) -> None:
    """Load env files: shared LangGraph `code/.env` (or RENTAL_RAG_SHARED_ENV_FILE), then project `.env` for gaps.

    Order ensures OPENAI_* / COMET_* from LangGraph win; LINE / paths only in rental_rag_poc/.env still apply.
    """
    global _implicit_shared_warned, _last_env_bootstrap

    root = project_root or Path(__file__).resolve().parent.parent
    langgraph_resolved = (root / _SHARED_ENV_RELATIVE).resolve()
    meta: Dict[str, Any] = {
        "mode": "bootstrap",
        "project_root": str(root.resolve()),
        "rental_rag_shared_env_file_var": None,
        "loaded_override_path": None,
        "langgraph_candidate": str(langgraph_resolved),
        "rental_env_path": str((root / ".env").resolve()),
        "rental_env_loaded": False,
        "fallback_load_dotenv_cwd": False,
    }
    shared_override = os.environ.get("RENTAL_RAG_SHARED_ENV_FILE", "").strip()
    if shared_override:
        meta["rental_rag_shared_env_file_var"] = shared_override
        sp = Path(shared_override).expanduser()
        if not sp.is_file():
            raise RuntimeError(
                f"RENTAL_RAG_SHARED_ENV_FILE is set but file not found: {sp.resolve()}. "
                "Fix the path or unset the variable."
            )
        load_dotenv(sp, override=True)
        meta["loaded_override_path"] = str(sp.resolve())
    else:
        if langgraph_resolved.is_file():
            if "RENTAL_RAG_SHARED_ENV_FILE" not in os.environ and not _implicit_shared_warned:
                logger.warning(
                    "RENTAL_RAG_SHARED_ENV_FILE not set; loading sibling shared .env at %s "
                    "(export RENTAL_RAG_SHARED_ENV_FILE to pin an explicit path).",
                    langgraph_resolved,
                )
                _implicit_shared_warned = True
            load_dotenv(langgraph_resolved, override=True)
            meta["loaded_override_path"] = str(langgraph_resolved)

    rental_env = root / ".env"
    if rental_env.is_file():
        load_dotenv(rental_env, override=False)
        meta["rental_env_loaded"] = True
    elif not shared_override and not langgraph_resolved.is_file():
        load_dotenv()
        meta["fallback_load_dotenv_cwd"] = True

    _last_env_bootstrap = meta


def reset_config() -> None:
    """Clear cached config (tests / scripts)."""
    global _config, _last_env_bootstrap, _implicit_shared_warned
    _config = None
    _last_env_bootstrap = {}
    _implicit_shared_warned = False


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
