"""Supabase JWKS(공개키) 조회와 캐시.

Supabase는 프로젝트마다 ES256 비대칭 키로 JWT를 서명한다. 서버는 공개키만
가지면 검증할 수 있고, 비밀키를 보관할 필요가 없다. HS256 공유 시크릿 방식보다
안전한 이유가 이것이다 — 검증자가 토큰을 위조할 수 없다.

공개키는 회전(rotation)되므로 캐시하되 만료시간을 둔다. 모르는 kid를 만나면
즉시 다시 받아온다.
"""

from __future__ import annotations

import logging
import time

import httpx
import jwt

from app.core.config import Settings

logger = logging.getLogger(__name__)


class JwksUnavailableError(RuntimeError):
    """공개키를 가져올 수 없음. 인증을 통과시키지 않고 실패시킨다."""


class JwksCache:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0

    @property
    def _expired(self) -> bool:
        return time.monotonic() - self._fetched_at > self._settings.jwks_cache_seconds

    async def _fetch(self) -> None:
        url = self._settings.jwks_url
        if not url:
            raise JwksUnavailableError("SUPABASE_URL이 설정되지 않아 JWKS를 조회할 수 없습니다.")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise JwksUnavailableError(f"JWKS 조회 실패: {exc}") from exc

        keys: dict[str, jwt.PyJWK] = {}
        for entry in payload.get("keys", []):
            kid = entry.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = jwt.PyJWK.from_dict(entry)
            except Exception as exc:
                logger.info("JWKS 키 파싱 실패 kid=%s: %s", kid, exc)
        if not keys:
            raise JwksUnavailableError("JWKS에 사용 가능한 키가 없습니다.")

        self._keys = keys
        self._fetched_at = time.monotonic()
        logger.info("JWKS 갱신됨: %d개 키", len(keys))

    async def get(self, kid: str) -> jwt.PyJWK:
        if self._expired or kid not in self._keys:
            # 모르는 kid는 키 회전 직후일 수 있으므로 다시 받아본다.
            await self._fetch()
        key = self._keys.get(kid)
        if key is None:
            raise JwksUnavailableError(f"알 수 없는 키 식별자입니다: {kid}")
        return key

    def clear(self) -> None:
        self._keys.clear()
        self._fetched_at = 0.0


_cache: JwksCache | None = None


def get_jwks_cache(settings: Settings) -> JwksCache:
    global _cache
    if _cache is None:
        _cache = JwksCache(settings)
    return _cache


def reset_jwks_cache() -> None:
    global _cache
    _cache = None
