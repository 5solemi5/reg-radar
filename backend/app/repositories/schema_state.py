"""적용되지 않은 마이그레이션 감지 (운영 드리프트 탐지).

Render 무료 티어는 pre-deploy 명령을 지원하지 않는다. 그래서 배포할 때
마이그레이션이 자동으로 돌지 않는데, **그 사실이 조용하다는 것**이 진짜 위험이다.
스키마가 코드보다 뒤처진 채로 서비스가 정상인 척 뜨고, 새 칼럼을 읽는 순간
UndefinedColumnError로 처음 드러난다.

자동으로 적용하지는 않는다. 기동 중 마이그레이션은 실패하면 서비스 자체를
못 뜨게 만들고, 인스턴스가 여러 개면 서로 경쟁한다. 대신 **감지해서 말한다** —
기동 로그에 경고를 남기고 /health에 목록을 싣는다.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


def migration_filenames() -> list[str]:
    return sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))


async def pending_migrations(db) -> list[str]:
    """파일로는 있는데 schema_migrations에 기록이 없는 마이그레이션.

    추적 테이블이 아예 없으면 한 번도 적용하지 않은 것이므로 전부 반환한다.
    조회에 실패하면 빈 목록을 돌려준다 — 이 정보 때문에 헬스 체크가 실패하면
    안 되기 때문이다. 없는 것을 있다고 말하는 쪽이 더 나쁘다.
    """
    files = migration_filenames()
    if not files:
        return []
    try:
        rows = await db.fetch("SELECT filename FROM schema_migrations")
    except Exception as exc:
        if "schema_migrations" in str(exc):
            return files
        logger.warning("마이그레이션 상태를 확인하지 못했습니다: %s", exc)
        return []
    applied = {r["filename"] for r in rows}
    return [name for name in files if name not in applied]
