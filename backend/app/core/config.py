"""애플리케이션 설정. 모든 secret은 환경변수/.env에서만 읽는다 (NFR-008)."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 값 앞뒤 공백을 걷어낸다. 로컬 .env는 dotenv가 알아서 해 주지만 호스팅
        # 대시보드에 붙여넣을 때는 그대로 들어간다. URL 앞의 공백 하나로
        # JWKS 조회가 실패하는데, 그 원인을 찾기까지가 오래 걸린다.
        str_strip_whitespace=True,
    )

    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"

    # --- LLM (AP-02) ---
    openai_api_key: str = ""
    # 기본 모델은 측정으로 결정한다. applicability_v1 기준 gpt-4o-mini는
    # Q4 재현율 60%로 NFR-003(≥90%)을 충족하지 못했고, gpt-4o는 100%였다.
    # evaluation/results/ 참조.
    llm_model: str = "gpt-4o"
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
    # RAG를 끄면 참고자료 없이 분석한다. BR-005에 따라 정상 상태이며,
    # 인덱스를 아직 만들지 않은 환경에서 기본값으로 쓴다.
    daily_analysis_limit_per_user: int = 10
    """사용자 1명이 하루에 돌릴 수 있는 분석 수. 0이면 제한 없음.

    '동시 1건' 제약(uq_analyses_one_active_per_user)은 중복 클릭을 막을 뿐
    하루에 몇 번이든 돌리는 것을 막지 못한다. 가입이 열린 공개 배포에서는
    그것이 곧 OpenAI 키를 열어 두는 것과 같다. 분석 1회가 약 6만 토큰이다.
    """

    daily_analysis_limit_total: int = 200
    """전체 사용자 합산 일일 상한. 계정을 여러 개 만드는 경우를 막는다. 0이면 제한 없음."""

    decree_pairing_enabled: bool = True
    """위임된 하위법령 조문을 함께 조회할지 (ADR-025).

    끄면 위임 문구만 보고 보류하는 이전 동작으로 돌아간다. 법제처 호출이 법령당
    1~2건 늘어나므로 장애 시 끌 수 있게 플래그로 둔다.
    """

    rag_enabled: bool = False
    chroma_persist_dir: str = ".chroma"
    pinecone_api_key: str = ""
    pinecone_index: str = "reg-radar"
    rag_top_k: int = 5

    # --- 저장소 ---
    # memory: 인메모리. 프로세스 재시작 시 소실되며 로컬 실험용이다.
    # postgres: Supabase 또는 로컬 Postgres.
    storage: Literal["memory", "postgres"] = "memory"
    database_url: str = Field(
        "", description="postgresql://user:pass@host:5432/db · Supabase는 Connection string"
    )
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_command_timeout: float = 30.0

    # --- Supabase / 인증 ---
    supabase_url: str = ""
    # service_role 키는 두지 않는다. 인증은 JWKS 공개키로 JWT를 검증하는 방식이라
    # 필요가 없는데, 설정에 자리가 있으면 배포할 때 누군가 채우게 된다. 그 키는
    # RLS를 통째로 우회하므로, 쓰지도 않을 것을 한 곳 더 두는 것은 손해뿐이다.
    # Supabase는 이제 프로젝트마다 ES256 비대칭 키로 JWT를 서명한다. 공개키는
    # JWKS 엔드포인트에서 받는다. HS256 공유 시크릿은 레거시 방식이며,
    # 레거시 키를 아직 쓰는 프로젝트를 위해 함께 지원한다.
    supabase_jwt_secret: str = ""
    jwks_cache_seconds: int = 3600
    # dev: X-User-Id 헤더를 그대로 신뢰한다. 로컬 개발 전용이며 production에서 금지.
    # supabase: Supabase JWT를 검증한다.
    auth_mode: Literal["dev", "supabase"] = "dev"
    dev_user_id: str = "dev-user"

    # --- API ---
    # localhost와 127.0.0.1은 브라우저에게 서로 다른 origin이다. 로컬 개발에서
    # 어느 쪽으로 접속하든 동작하도록 둘 다 허용한다.
    # 운영 도메인은 CORS_ORIGINS에 콤마로 구분해 넣는다.
    # NoDecode가 필요한 이유: pydantic-settings는 list 타입 환경변수를 JSON으로
    # 먼저 파싱하려 하고, 실패하면 validator가 실행되기 전에 예외를 던진다.
    # 즉 NoDecode 없이 아래 validator만 두면 콤마 구분 값이 동작하지 않는다.
    # (컨테이너를 실제로 띄워보고서야 발견했다.)
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        """콤마로 구분한 문자열을 목록으로 바꾼다.

        배포 플랫폼의 환경변수 입력란에 JSON 배열을 넣는 것은 실수하기 쉽다.
        `https://a.com,https://b.com` 형태를 받는다.
        """
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value
    api_prefix: str = "/api/v1"

    # --- 판정 정책 (BR-003) ---
    hold_confidence_threshold: float = Field(
        0.6, description="이 값 미만의 confidence는 APPLICABLE로 확정하지 않고 HOLD로 내린다."
    )

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        """운영에서 조용히 잘못 뜨는 것보다 기동을 막는 편이 낫다.

        dev 인증은 헤더를 그대로 믿고, 인메모리 저장소는 재시작 시 사용자
        데이터를 잃는다. 둘 다 배포 후에 발견하면 이미 늦다.
        """
        if self.app_env != "production":
            return self

        problems: list[str] = []
        if self.auth_mode == "dev":
            problems.append("AUTH_MODE=dev는 X-User-Id 헤더를 그대로 신뢰합니다")
        if self.storage == "memory":
            problems.append("STORAGE=memory는 재시작 시 모든 데이터를 잃습니다")
        if self.storage == "postgres" and not self.database_url:
            problems.append("STORAGE=postgres인데 DATABASE_URL이 없습니다")
        if self.auth_mode == "supabase" and not (
            self.supabase_url or self.supabase_jwt_secret
        ):
            problems.append("SUPABASE_URL 또는 SUPABASE_JWT_SECRET이 필요합니다")
        if any(o.startswith("http://localhost") for o in self.cors_origins):
            problems.append("CORS_ORIGINS에 localhost가 남아 있습니다")

        if problems:
            raise ValueError(
                "운영 환경 설정에 문제가 있습니다:\n  - " + "\n  - ".join(problems)
            )
        return self

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def law_api_enabled(self) -> bool:
        return bool(self.law_api_oc)

    @property
    def postgres_enabled(self) -> bool:
        return self.storage == "postgres" and bool(self.database_url)

    @property
    def jwks_url(self) -> str:
        """Supabase 프로젝트의 공개키 목록. 공개 정보이므로 비밀이 아니다."""
        base = self.supabase_url.rstrip("/")
        return f"{base}/auth/v1/.well-known/jwks.json" if base else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
