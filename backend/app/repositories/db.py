"""Postgres 연결 관리 (W4).

Supabase는 관리형 Postgres이므로 asyncpg로 직접 연결한다. PostgREST를 거치지
않는 이유는, 저장소 계층이 이미 Protocol로 분리되어 있어 SQL을 직접 쓰는 편이
쿼리 의도를 드러내기 좋고, 로컬 Postgres에서 그대로 테스트할 수 있기 때문이다.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """DB 연결 실패 (ER-008). 저장 실패를 완료로 응답하지 않기 위해 예외로 올린다."""


async def _init_connection(connection: asyncpg.Connection) -> None:
    """jsonb를 파이썬 dict/list로 자동 변환한다.

    주의: 이 코덱을 설치하면 jsonb 파라미터에 **dict/list를 그대로** 넘겨야 한다.
    미리 json.dumps한 문자열을 넘기면 코덱이 한 번 더 직렬화해서 JSON 문자열이
    저장되고, 읽을 때 dict가 아니라 str이 돌아온다.
    """
    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            encoder=lambda value: json.dumps(value, ensure_ascii=False),
            decoder=json.loads,
            schema="pg_catalog",
        )


class Database:
    """커넥션 풀 보유자. 앱 수명과 함께 산다."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise DatabaseUnavailableError("데이터베이스 풀이 초기화되지 않았습니다.")
        return self._pool

    @property
    def is_connected(self) -> bool:
        return self._pool is not None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        if not self.settings.database_url:
            raise DatabaseUnavailableError("DATABASE_URL이 설정되지 않았습니다.")
        try:
            self._pool = await asyncpg.create_pool(
                dsn=self.settings.database_url,
                min_size=self.settings.db_pool_min,
                max_size=self.settings.db_pool_max,
                command_timeout=self.settings.db_command_timeout,
                init=_init_connection,
            )
        except Exception as exc:
            logger.warning("데이터베이스 연결 실패: %s", exc)
            raise DatabaseUnavailableError(f"데이터베이스에 연결할 수 없습니다: {exc}") from exc
        logger.info("데이터베이스 연결됨")

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ── 편의 래퍼 ─────────────────────────────────────────────────────
    # asyncpg 예외를 그대로 올리면 상위 계층이 asyncpg에 결합된다.

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        async with self.pool.acquire() as connection:
            return await connection.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self.pool.acquire() as connection:
            return await connection.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        async with self.pool.acquire() as connection:
            return await connection.execute(query, *args)

    async def executemany(self, query: str, args_list: list[tuple]) -> None:
        async with self.pool.acquire() as connection:
            await connection.executemany(query, args_list)


_database: Database | None = None


def get_database(settings: Settings | None = None) -> Database:
    global _database
    if _database is None:
        _database = Database(settings)
    return _database


def reset_database() -> None:
    """테스트에서 전역 상태를 초기화한다."""
    global _database
    _database = None
