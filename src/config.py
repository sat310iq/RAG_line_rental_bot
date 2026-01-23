"""Configuration management with environment variable loading and validation."""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    """Application configuration loaded from environment variables."""
    
    # OpenAI Configuration (Required)
    openai_api_key: str = Field(..., description="OpenAI API key")
    
    # Model Configuration
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model"
    )
    openai_model: str = Field(
        default="gpt-5-mini",
        description="OpenAI chat model"
    )
    
    # Vector Store Configuration
    rag_vector_store_path: str = Field(
        default="data/vector_store",
        description="Path to ChromaDB persistent directory"
    )
    rag_retrieval_k: int = Field(
        default=5,
        description="Number of documents to retrieve per source"
    )
    rag_rerank_candidates: int = Field(
        default=20,
        description="Number of candidates for reranking"
    )
    rag_rerank_top_n: int = Field(
        default=3,
        description="Number of top documents after reranking"
    )
    rag_search_timeout_sec: float = Field(
        default=3.0,
        description="Timeout for search operations in seconds"
    )
    
    # Data Source Paths
    pdf_documents_dir: str = Field(
        default="data/documents",
        description="Directory containing PDF documents"
    )
    faq_csv_path: str = Field(
        default="data/dispute_guideline_faq.csv",
        description="Path to FAQ CSV file"
    )
    ops_log_csv_path: str = Field(
        default="data/faq_data.csv",
        description="Path to operations log CSV file"
    )
    tenant_master_csv: str = Field(
        default="data/tenants.csv",
        description="Path to tenant master CSV file"
    )
    
    # Operational Settings
    force_reindex_rental_qa: bool = Field(
        default=False,
        description="Force reindexing on startup"
    )
    enable_query_cache: bool = Field(
        default=True,
        description="Enable query result caching"
    )
    cache_ttl_sec: int = Field(
        default=3600,
        description="Cache TTL in seconds"
    )
    
    # Comet/OPIK Configuration (Optional)
    comet_api_key: Optional[str] = Field(
        default=None,
        description="Comet API key for evaluation logging (optional)"
    )
    comet_project_name: str = Field(
        default="rental-rag-poc",
        description="Comet project name"
    )
    comet_workspace: Optional[str] = Field(
        default=None,
        description="Comet workspace name"
    )
    enable_comet_logging: bool = Field(
        default=False,
        description="Enable Comet logging for evaluation (default: False)"
    )
    
    @field_validator("openai_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate that API key is provided."""
        if not v or v == "your_openai_api_key_here":
            raise ValueError("OPENAI_API_KEY must be set in .env file")
        return v
    
    @field_validator("rag_retrieval_k", "rag_rerank_candidates", "rag_rerank_top_n")
    @classmethod
    def validate_positive_int(cls, v: int) -> int:
        """Validate that integer values are positive."""
        if v <= 0:
            raise ValueError(f"Value must be positive, got {v}")
        return v
    
    @field_validator("rag_search_timeout_sec")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        """Validate that timeout is positive."""
        if v <= 0:
            raise ValueError(f"Timeout must be positive, got {v}")
        return v
    
    def get_vector_store_path(self) -> Path:
        """Get vector store path as Path object."""
        return Path(self.rag_vector_store_path)
    
    def get_pdf_documents_dir(self) -> Path:
        """Get PDF documents directory as Path object."""
        return Path(self.pdf_documents_dir)
    
    def get_faq_csv_path(self) -> Path:
        """Get FAQ CSV path as Path object."""
        return Path(self.faq_csv_path)
    
    def get_ops_log_csv_path(self) -> Path:
        """Get operations log CSV path as Path object."""
        return Path(self.ops_log_csv_path)
    
    def get_tenant_master_csv_path(self) -> Path:
        """Get tenant master CSV path as Path object."""
        return Path(self.tenant_master_csv)


# Global config instance
_config: Optional[Config] = None


def load_config(env_file: Optional[str] = None) -> Config:
    """Load configuration from environment variables.
    
    Args:
        env_file: Optional path to .env file. Defaults to .env in project root.
        
    Returns:
        Config instance with validated settings.
    """
    global _config
    
    if _config is None:
        # Load .env file
        if env_file:
            load_dotenv(env_file)
        else:
            # Try to find .env in project root
            project_root = Path(__file__).parent.parent
            env_path = project_root / ".env"
            if env_path.exists():
                load_dotenv(env_path)
            else:
                load_dotenv()  # Try default locations
        
        # Create config from environment variables
        _config = Config(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            rag_vector_store_path=os.getenv("RAG_VECTOR_STORE_PATH", "data/vector_store"),
            rag_retrieval_k=int(os.getenv("RAG_RETRIEVAL_K", "5")),
            rag_rerank_candidates=int(os.getenv("RAG_RERANK_CANDIDATES", "20")),
            rag_rerank_top_n=int(os.getenv("RAG_RERANK_TOP_N", "3")),
            rag_search_timeout_sec=float(os.getenv("RAG_SEARCH_TIMEOUT_SEC", "3.0")),
            pdf_documents_dir=os.getenv("PDF_DOCUMENTS_DIR", "data/documents"),
            faq_csv_path=os.getenv("FAQ_CSV_PATH", "data/dispute_guideline_faq.csv"),
            ops_log_csv_path=os.getenv("OPS_LOG_CSV_PATH", "data/faq_data.csv"),
            tenant_master_csv=os.getenv("TENANT_MASTER_CSV", "data/tenants.csv"),
            force_reindex_rental_qa=os.getenv("FORCE_REINDEX_RENTAL_QA", "false").lower() == "true",
            enable_query_cache=os.getenv("ENABLE_QUERY_CACHE", "true").lower() == "true",
            cache_ttl_sec=int(os.getenv("CACHE_TTL_SEC", "3600")),
            comet_api_key=os.getenv("COMET_API_KEY") or None,
            comet_project_name=os.getenv("COMET_PROJECT_NAME", "rental-rag-poc"),
            comet_workspace=os.getenv("COMET_WORKSPACE") or None,
            enable_comet_logging=os.getenv("ENABLE_COMET_LOGGING", "false").lower() == "true",
        )
    
    return _config


def get_config() -> Config:
    """Get the global config instance, loading if necessary."""
    if _config is None:
        return load_config()
    return _config
