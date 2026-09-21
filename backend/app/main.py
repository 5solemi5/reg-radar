"""FastAPI 애플리케이션 (04 설계서 §3 ②계층, ADR-002/ADR-006).

modular monolith: Application Service와 AI Core를 한 프로세스 안에 두되
모듈 경계는 분리한다. 마이크로서비스로 쪼개지 않는다.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import ApiError, api_error_handler, unhandled_error_handler
from app.api.routers import analyses, health, profile, results
from app.core.config import Settings, get_settings
from app.repositories.db import get_database

logger = logging.getLogger(__name__)

DESCRIPTION = """\
내 업무에 영향을 주는 규제 변화만 골라, 왜 중요한지와 지금 무엇을 해야 하는지를
근거와 함께 알려주는 API.

**근거의 성격을 섞지 않습니다.** 응답의 `legal_evidence`는 법제처 공식 원문,
`reference_evidence`는 RAG 참고자료, `ai_interpretation`은 모델의 해석입니다.
법령명·조문번호·시행일은 모델이 생성하지 않습니다.

이 서비스는 법률 자문이 아닙니다.
"""


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def build_lifespan(settings: Settings):
    """DB 커넥션 풀을 앱 수명에 맞춘다."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database = get_database(settings)
        if settings.postgres_enabled:
            # 여기서 실패하면 기동을 막는다. DB 없이 뜬 서버는 모든 저장 요청을
            # 실패시키므로, 조용히 뜨는 것보다 시작을 거부하는 편이 낫다.
            await database.connect()
        yield
        if database.is_connected:
            await database.disconnect()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    # dev 인증은 X-User-Id 헤더를 그대로 믿는다. 운영에서 이 조합은 인증이
    # 없는 것과 같으므로 기동을 거부한다 (NFR-007).
    if settings.app_env == "production" and settings.auth_mode == "dev":
        raise RuntimeError(
            "production에서 auth_mode=dev는 허용되지 않습니다. AUTH_MODE=supabase로 설정하세요."
        )

    if settings.storage == "postgres" and not settings.database_url:
        raise RuntimeError("STORAGE=postgres에는 DATABASE_URL이 필요합니다.")

    app = FastAPI(
        lifespan=build_lifespan(settings),
        title="규제 변화 AI 도우미 API",
        description=DESCRIPTION,
        version="0.2.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-User-Id"],
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    prefix = settings.api_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(profile.router, prefix=prefix)
    app.include_router(analyses.router, prefix=prefix)
    app.include_router(results.router, prefix=prefix)

    logger.info(
        "앱 기동 env=%s auth=%s storage=%s law_api=%s llm=%s",
        settings.app_env, settings.auth_mode, settings.storage,
        settings.law_api_enabled, settings.llm_enabled,
    )
    return app


app = create_app()
