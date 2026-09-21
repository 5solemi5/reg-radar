"""마이그레이션 적용기.

`DATABASE_URL`이 가리키는 DB에 `migrations/*.sql`을 순서대로 적용한다.
Supabase SQL Editor에 복사-붙여넣기 하지 않아도 되고, 무엇을 적용했는지
`schema_migrations` 테이블에 기록해 두 번 실행해도 안전하다.

    .venv/bin/python scripts/migrate.py            # 적용
    .venv/bin/python scripts/migrate.py --status   # 적용 현황만 확인
    .venv/bin/python scripts/migrate.py --dry-run  # 무엇이 적용될지만 표시
"""

import argparse
import asyncio
import hashlib
import re
from pathlib import Path

import asyncpg

from app.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

# Supabase 전용 마이그레이션은 auth.uid()를 쓴다. 로컬 Postgres에는 없다.
SUPABASE_ONLY = re.compile(r"auth\.(uid|role)\s*\(")

TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


def migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def has_supabase_auth(connection: asyncpg.Connection) -> bool:
    """auth.uid() 함수가 있는지로 Supabase 여부를 판단한다."""
    return bool(
        await connection.fetchval(
            """
            SELECT 1 FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'auth' AND p.proname = 'uid'
            LIMIT 1
            """
        )
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="적용 현황만 확인")
    parser.add_argument("--dry-run", action="store_true", help="적용하지 않고 계획만 표시")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        print("✗ DATABASE_URL이 설정되지 않았습니다. backend/.env를 확인하세요.")
        return 1

    # 비밀번호가 화면이나 로그에 남지 않도록 호스트만 표시한다.
    safe = re.sub(r"://[^@]+@", "://***@", settings.database_url)
    print(f"▶ 대상: {safe}\n")

    try:
        connection = await asyncpg.connect(settings.database_url, timeout=20)
    except Exception as exc:
        print(f"✗ 연결 실패: {type(exc).__name__}: {exc}")
        print("  · DATABASE_URL의 비밀번호와 호스트를 확인하세요.")
        print("  · Supabase는 Session pooler 연결 문자열을 권장합니다.")
        return 1

    try:
        is_supabase = await has_supabase_auth(connection)
        print(f"▶ 환경: {'Supabase' if is_supabase else '일반 Postgres'}")
        await connection.execute(TRACKING_TABLE)

        applied = {
            row["filename"]: row["checksum"]
            for row in await connection.fetch("SELECT filename, checksum FROM schema_migrations")
        }

        files = migration_files()
        if not files:
            print("✗ migrations/*.sql 파일이 없습니다.")
            return 1

        print(f"▶ 마이그레이션 {len(files)}개\n")
        pending: list[Path] = []
        for path in files:
            digest = checksum(path)
            supabase_only = SUPABASE_ONLY.search(path.read_text(encoding="utf-8")) is not None

            if path.name in applied:
                changed = applied[path.name] != digest
                mark = "⚠️ 적용 후 내용이 바뀜" if changed else "✓ 적용됨"
                print(f"  {mark}  {path.name}")
                if changed:
                    print("      이미 적용된 파일이 수정되었습니다.")
                    print("      새 마이그레이션 파일로 분리하세요.")
                continue

            if supabase_only and not is_supabase:
                print(f"  – 건너뜀  {path.name} (Supabase 전용: auth.uid 사용)")
                continue

            print(f"  → 적용 예정  {path.name}")
            pending.append(path)

        if args.status:
            return 0
        if not pending:
            print("\n✓ 적용할 마이그레이션이 없습니다.")
            return 0
        if args.dry_run:
            print(f"\n(dry-run) {len(pending)}개가 적용될 예정입니다.")
            return 0

        print()
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            try:
                # 마이그레이션 1개를 트랜잭션으로 묶는다. 중간에 실패하면 통째로 되돌린다.
                async with connection.transaction():
                    await connection.execute(sql)
                    await connection.execute(
                        "INSERT INTO schema_migrations (filename, checksum) VALUES ($1, $2)",
                        path.name,
                        checksum(path),
                    )
            except Exception as exc:
                print(f"✗ {path.name} 적용 실패 — 롤백됨")
                print(f"  {type(exc).__name__}: {exc}")
                return 1
            print(f"✓ {path.name} 적용 완료")

        tables = await connection.fetch(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename <> 'schema_migrations'
            ORDER BY tablename
            """
        )
        print(f"\n▶ public 스키마 테이블 {len(tables)}개")
        for row in tables:
            print(f"    {row['tablename']}")
        return 0
    finally:
        await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
