"""
应用配置模块
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    """应用配置"""

    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl: int = 3600

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection_name: str = "rag_documents"

    # MinIO
    minio_url: str = "http://localhost:9000"
    minio_console_url: str = "http://localhost:9001"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin_password_dev"
    minio_bucket: str = "knowledge-base"

    # Security
    secret_key: str = "dev-secret-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # LLM Configuration
    claude_api_key: Optional[str] = None
    claude_api_base: Optional[str] = None
    gpt4_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_api_base: str = "https://api.deepseek.com"
    embedding_model: str = "BAAI/bge-small-zh"
    rerank_model_path: str = "/app/models/reranker/models/BAAI--bge-reranker-base/snapshots/master"
    claude_model_haiku: str = "claude-3-5-haiku-20241022"
    claude_model_sonnet: str = "claude-3-5-sonnet-20241022"
    gpt4_model: str = "gpt-4o"
    deepseek_model: str = "deepseek-chat"
    answer_max_tokens: int = Field(default=4096, ge=1, le=32768)
    answer_timeout_seconds: float = Field(default=90, gt=0, le=110)
    llm_provider: str = "deepseek"  # 可选: deepseek, claude, gpt4

    # Feature Flags
    enable_rerank: bool = True
    enable_audit_log: bool = True
    enable_cache: bool = True

    # Scanned PDF OCR
    pdf_ocr_enabled: bool = True
    pdf_ocr_lang: str = "ch"
    pdf_ocr_dpi: int = Field(default=200, ge=72, le=400)
    pdf_ocr_min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pdf_scanned_min_chars: int = Field(default=50, ge=0)
    pdf_max_upload_mb: int = Field(default=200, ge=1)
    pdf_pages_dir: str = "/app/docs/pdf_pages"
    pdf_source_dir: str = "/app/docs/pdf_source"
    pdf_ocr_max_retries: int = Field(default=3, ge=1, le=5)
    pdf_ocr_max_workers: int = Field(default=4, ge=1, le=8)
    pdf_ocr_profile: str = "default"  # default, medical_scan, dense_table

    # Controlled RAG Agent (方案 B)
    rag_agent_enabled: bool = False
    rag_agent_default_mode: str = "simple"
    rag_agent_max_retrieval_attempts: int = Field(default=2, ge=1, le=2)
    rag_agent_recovery_top_k: int = Field(default=6, ge=2, le=20)
    rag_agent_min_results: int = Field(default=1, ge=1, le=10)
    rag_agent_min_score: Optional[float] = None
    rag_agent_clarify_on_missing_hospital: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

# 全局配置实例
settings = Settings()
