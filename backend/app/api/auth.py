"""인증 (FR-001, NFR-007, ER-007).

W2에서는 dev 모드로 동작한다. W3에서 Supabase JWT 검증을 붙이되, 라우터가
의존하는 것은 `CurrentUser`뿐이므로 교체가 라우터로 번지지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Request

from app.api.errors import UnauthorizedError
from app.api.jwks import JwksUnavailableError, get_jwks_cache
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


# 허용 알고리즘을 고정한다. 토큰이 알고리즘을 고르게 두면 `alg: none` 공격에 열린다.
_ASYMMETRIC_ALGORITHMS = ["ES256", "RS256"]
_SYMMETRIC_ALGORITHMS = ["HS256"]


def _decode_claims(token: str, key, algorithms: list[str]) -> dict:
    """공통 검증 규칙. 서명·만료·audience·필수 클레임을 모두 확인한다."""
    return jwt.decode(
        token,
        key,
        algorithms=algorithms,
        audience="authenticated",
        options={"require": ["sub", "exp"]},
    )


async def _supabase_user(settings: Settings, token: str | None) -> CurrentUser:
    """Supabase가 발급한 JWT를 검증한다.

    Supabase는 프로젝트마다 ES256 비대칭 키로 서명하며, 공개키를 JWKS로 배포한다.
    서버가 공개키만 가지면 되므로 HS256 공유 시크릿보다 안전하다 — 검증자가
    토큰을 위조할 수 없기 때문이다. 레거시 HS256 프로젝트를 위해 공유 시크릿
    방식도 함께 지원한다.
    """
    if not token:
        raise UnauthorizedError()

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError(detail="토큰 헤더를 읽을 수 없습니다.") from exc

    algorithm = header.get("alg")
    kid = header.get("kid")

    try:
        if algorithm in _ASYMMETRIC_ALGORITHMS and kid:
            if not settings.jwks_url:
                raise UnauthorizedError(
                    "인증 설정이 완료되지 않았습니다.", detail="SUPABASE_URL 없음"
                )
            signing_key = await get_jwks_cache(settings).get(kid)
            claims = _decode_claims(token, signing_key.key, _ASYMMETRIC_ALGORITHMS)
        elif algorithm in _SYMMETRIC_ALGORITHMS:
            if not settings.supabase_jwt_secret:
                # 비밀키가 없는데 통과시키면 인증이 없는 것과 같다. 열지 않고 막는다.
                raise UnauthorizedError(
                    "인증 설정이 완료되지 않았습니다.", detail="SUPABASE_JWT_SECRET 없음"
                )
            claims = _decode_claims(
                token, settings.supabase_jwt_secret, _SYMMETRIC_ALGORITHMS
            )
        else:
            raise UnauthorizedError(detail=f"지원하지 않는 서명 알고리즘: {algorithm}")
    except JwksUnavailableError as exc:
        # 공개키를 못 가져오면 통과시키지 않는다. 열어두면 인증이 없는 것과 같다.
        logger.warning("JWKS 사용 불가: %s", exc)
        raise UnauthorizedError("인증 서버에 연결할 수 없습니다.", detail=str(exc)) from exc
    except jwt.ExpiredSignatureError as exc:
        # ER-007. 만료는 재로그인으로 풀리는 상태이므로 구분해 알려준다.
        raise UnauthorizedError("세션이 만료되었습니다. 다시 로그인해 주세요.") from exc
    except jwt.InvalidTokenError as exc:
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
        else await _supabase_user(settings, _bearer_token(authorization))
    )
    if not user.user_id:
        raise UnauthorizedError()
    # 관측성: trace에 사용자 식별자를 남기되 토큰 원문은 남기지 않는다 (NFR-009).
    request.state.user_id = user.user_id
    return user
