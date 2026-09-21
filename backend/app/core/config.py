"""애플리케이션 설정. 모든 secret은 환경변수/.env에서만 읽는다 (NFR-008)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"

    # --- LLM (AP-02) ---
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # --- 법제처 OPEN API (AP-01) ---
    # OC = open.law.go.kr 가입 이메일의 @ 앞부분
    law_api_oc: str = ""
    law_api_base_url: str = "https://www.law.go.kr/DRF"
    law_api_timeout_seconds: float = 20.0
    law_api_max_retries: int = 2

    # --- RAG / Vector DB (W5에서 사용) ---
    embedding_model: str = "text-embedding-3-small"
    vector_store: Literal["chroma", "pinecone"] = "chroma"
    chroma_persist_dir: str = ".chroma"
    pinecone_api_key: str = ""
    pinecone_index: str = "reg-radar"
    rag_top_k: int = 5

    # --- Supabase (W3에서 사용) ---
    supabase_url: str = ""
    supabase_service_key: str = ""

    # --- 판정 정책 (BR-003) ---
    hold_confidence_threshold: float = Field(
        0.6, description="이 값 미만의 confidence는 APPLICABLE로 확정하지 않고 HOLD로 내린다."
    )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def law_api_enabled(self) -> bool:
        return bool(self.law_api_oc)


@lru_cache
def get_settings() -> Settings:
    return Settings()
