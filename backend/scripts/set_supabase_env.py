"""Supabase 연결 정보를 .env에 안전하게 기록한다.

값을 **클립보드에서** 읽는다. 명령행 인자로 받으면 셸 히스토리와 로그에 비밀값이
남고, 대화형 입력은 TTY가 없는 환경에서 동작하지 않기 때문이다.

    # 1) Connect → Session pooler 의 URI를 복사한 뒤
    .venv/bin/python scripts/set_supabase_env.py dsn

    # 2) Settings → API → JWT Secret 을 복사한 뒤
    .venv/bin/python scripts/set_supabase_env.py jwt

    # 현재 상태 확인 (값은 가려서 표시)
    .venv/bin/python scripts/set_supabase_env.py status
"""

import asyncio
import re
import secrets
import string
import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(__file__).parent.parent / ".env"


def write_clipboard(value: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=value, text=True, check=True, timeout=10)
    except Exception:
        return False
    return True


def generate_password(length: int = 32) -> str:
    """URL에 그대로 들어가므로 인코딩이 필요한 문자를 쓰지 않는다.

    @ : / ? # 같은 문자가 비밀번호에 있으면 연결 문자열 파싱이 깨진다.
    영숫자 32자면 충분히 강하다.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def read_clipboard() -> str:
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        print("✗ pbpaste를 찾을 수 없습니다 (macOS 전용).")
        return ""
    return result.stdout.strip()


def read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def write_env(updates: dict[str, str]) -> None:
    """기존 줄은 보존하고 지정한 키만 교체/추가한다."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    out: list[str] = []
    seen: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)

    missing = [k for k in updates if k not in seen]
    if missing:
        out.append("")
        out.append("# ── Supabase ────────────────────────────────")
        out.extend(f"{k}={updates[k]}" for k in missing)

    ENV_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def mask_dsn(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


async def test_connection(dsn: str) -> tuple[bool, str]:
    import asyncpg

    try:
        connection = await asyncpg.connect(dsn, timeout=25)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    try:
        version = await connection.fetchval("SELECT version()")
        return True, version.split(" on ")[0]
    finally:
        await connection.close()


def cmd_status() -> int:
    env = read_env()
    print("현재 .env 상태\n")
    for key in ("STORAGE", "AUTH_MODE", "SUPABASE_URL", "DATABASE_URL", "SUPABASE_JWT_SECRET"):
        value = env.get(key, "")
        if not value:
            print(f"  {key:22} ✗ 비어 있음")
        elif key == "DATABASE_URL":
            print(f"  {key:22} ✓ {mask_dsn(value)}")
        elif key == "SUPABASE_JWT_SECRET":
            print(f"  {key:22} ✓ {len(value)}자")
        else:
            print(f"  {key:22} ✓ {value}")
    return 0


def cmd_dsn() -> int:
    dsn = read_clipboard()
    if not dsn:
        print("✗ 클립보드가 비어 있습니다. 연결 문자열을 복사한 뒤 다시 실행하세요.")
        return 1

    if not dsn.startswith(("postgresql://", "postgres://")):
        print(f"✗ postgresql:// 로 시작해야 합니다. 복사된 값의 시작: {dsn[:24]!r}")
        print("  Connect → Session pooler 탭의 URI를 복사했는지 확인하세요.")
        return 1
    if "YOUR-PASSWORD" in dsn or re.search(r"\[[^\]]*\]", dsn):
        print("✗ [YOUR-PASSWORD] 자리가 그대로입니다. 실제 DB 비밀번호로 바꿔 복사하세요.")
        return 1

    print(f"▶ 클립보드에서 읽음: {mask_dsn(dsn)}")
    print("▶ 연결을 확인합니다…")
    ok, detail = asyncio.run(test_connection(dsn))
    if not ok:
        print(f"✗ 연결 실패: {detail}")
        print("\n  .env는 수정하지 않았습니다. 확인할 것:")
        print("  · DB 비밀번호가 정확한지 (프로젝트 생성 때 만든 것)")
        print("  · Direct connection이 아니라 Session pooler 문자열인지")
        return 1

    print(f"✓ 연결 성공 — {detail}")
    write_env({"DATABASE_URL": dsn, "STORAGE": "postgres"})
    print("✓ .env 기록 완료 (DATABASE_URL, STORAGE=postgres)")
    print("\n다음: JWT Secret을 복사한 뒤")
    print("  .venv/bin/python scripts/set_supabase_env.py jwt")
    return 0


def cmd_jwt() -> int:
    secret = read_clipboard()
    if not secret:
        print("✗ 클립보드가 비어 있습니다. JWT Secret을 복사한 뒤 다시 실행하세요.")
        return 1
    if secret.startswith(("postgresql://", "postgres://", "http")):
        print("✗ 연결 문자열이나 URL이 복사되어 있습니다. JWT Secret을 복사하세요.")
        return 1
    if len(secret) < 20:
        print(f"✗ 너무 짧습니다 ({len(secret)}자). JWT Secret은 보통 40자 이상입니다.")
        return 1

    write_env({"SUPABASE_JWT_SECRET": secret, "AUTH_MODE": "supabase"})
    print(f"✓ JWT Secret 기록 완료 ({len(secret)}자, AUTH_MODE=supabase)")
    print("\n다음: .venv/bin/python scripts/migrate.py")
    return 0


def cmd_prepare() -> int:
    """연결 문자열 템플릿을 받아 비밀번호를 생성하고 .env와 클립보드에 넣는다.

    비밀번호는 화면에 출력하지 않는다. Supabase 대시보드에는 클립보드에서
    붙여넣어 설정한다.
    """
    if len(sys.argv) < 3:
        print("사용법: set_supabase_env.py prepare '<connection string template>'")
        return 1

    template = sys.argv[2].strip()
    if not template.startswith(("postgresql://", "postgres://")):
        print("✗ postgresql:// 로 시작하는 연결 문자열이어야 합니다.")
        return 1
    if not re.search(r"\[[^\]]*PASSWORD[^\]]*\]", template):
        print("✗ [YOUR-PASSWORD] 자리가 없습니다. 템플릿을 그대로 넘겨주세요.")
        return 1

    password = generate_password()
    dsn = re.sub(r"\[[^\]]*PASSWORD[^\]]*\]", password, template)

    if not write_clipboard(password):
        print("✗ 클립보드에 복사하지 못했습니다 (pbcopy 필요).")
        return 1

    write_env({"DATABASE_URL": dsn, "STORAGE": "postgres"})
    print(f"✓ 비밀번호 생성 ({len(password)}자, 영숫자)")
    print(f"✓ .env 기록 완료 — {mask_dsn(dsn)}")
    print("✓ 비밀번호를 클립보드에 복사했습니다")
    print("\n다음: Supabase 대시보드에서 Reset password → 클립보드 붙여넣기")
    return 0


def cmd_verify() -> int:
    """.env의 DATABASE_URL로 실제 연결을 시도한다."""
    dsn = read_env().get("DATABASE_URL", "")
    if not dsn:
        print("✗ .env에 DATABASE_URL이 없습니다.")
        return 1
    print(f"▶ {mask_dsn(dsn)}")
    ok, detail = asyncio.run(test_connection(dsn))
    if not ok:
        print(f"✗ 연결 실패: {detail}")
        return 1
    print(f"✓ 연결 성공 — {detail}")
    return 0


COMMANDS = {
    "prepare": cmd_prepare,
    "verify": cmd_verify,
    "dsn": cmd_dsn,
    "jwt": cmd_jwt,
    "status": cmd_status,
}


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command not in COMMANDS:
        print(f"사용법: set_supabase_env.py [{' | '.join(COMMANDS)}]")
        return 1
    return COMMANDS[command]()


if __name__ == "__main__":
    sys.exit(main())
