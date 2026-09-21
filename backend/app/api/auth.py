"""인증 (FR-001, NFR-007, ER-007).

W2에서는 dev 모드로 동작한다. W3에서 Supabase JWT 검증을 붙이되, 라우터가
의존하는 것은 `CurrentUser`뿐이므로 교체가 라우터로 번지지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, Header, Request

from app.api.errors import UnauthorizedError
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None = None


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _dev_user(settings: Settings, x_user_id: str | None) -> CurrentUser:
    """로컬 개발용. 헤더의 사용자 ID를 그대로 신뢰한다.

    production에서 이 경로를 타면 인증이 없는 것과 같으므로 기동 시 차단한다
    (app.main.create_app 참조).
    """
    return CurrentUser(user_id=(x_user_id or settings.dev_user_id).strip())


def _supabase_user(settings: Settings, token: str | None) -> CurrentUser:
    if not token:
        raise UnauthorizedError()
    if not settings.supabase_jwt_secret:
        raise UnauthorizedError(
            "인증 설정이 완료되지 않았습니다.", detail="SUPABASE_JWT_SECRET 없음"
        )
    try:
        import jwt  # PyJWT — W3에서 의존성 추가
    except ImportError as exc:  # pragma: no cover
        raise UnauthorizedError(
            "인증 모듈을 사용할 수 없습니다.", detail="PyJWT 미설치"
        ) from exc

    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except Exception as exc:
        logger.info("JWT 검증 실패: %s", type(exc).__name__)
        raise UnauthorizedError(detail=type(exc).__name__) from exc

    user_id = claims.get("sub")
    if not user_id:
        raise UnauthorizedError(detail="sub 클레임 없음")
    return CurrentUser(user_id=user_id, email=claims.get("email"))


async def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    user = (
        _dev_user(settings, x_user_id)
        if settings.auth_mode == "dev"
        else _supabase_user(settings, _bearer_token(authorization))
    )
    if not user.user_id:
        raise UnauthorizedError()
    # 관측성: trace에 사용자 식별자를 남기되 토큰 원문은 남기지 않는다 (NFR-009).
    request.state.user_id = user.user_id
    return user
