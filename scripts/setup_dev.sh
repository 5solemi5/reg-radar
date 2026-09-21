#!/usr/bin/env bash
#
# 새 기기에서 개발 환경을 세운다.
#
# 저장소에 없는 것들(의존성·로컬 DB)을 만들고, 사람만 옮길 수 있는 것(비밀값)은
# 무엇이 왜 필요한지 알려주고 멈춘다. 몇 번을 실행해도 안전하다.
#
#   bash scripts/setup_dev.sh
#
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

ok()    { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn()  { printf "  \033[33m!\033[0m %s\n" "$1"; }
bad()   { printf "  \033[31m✗\033[0m %s\n" "$1"; }
head_() { printf "\n\033[1m%s\033[0m\n" "$1"; }

MISSING=0

# ── 1. 필수 도구 ─────────────────────────────────────────────────────
head_ "1. 필수 도구"
need() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "$1 — $("$1" --version 2>&1 | head -1)"
  else
    bad "$1 없음 — $2"
    MISSING=1
  fi
}
need python3.12 "brew install python@3.12"
need node       "brew install node"
need psql       "brew install postgresql@16 && brew services start postgresql@16"

# 패키지 매니저는 pnpm이다. package.json의 packageManager 필드와 pnpm-lock.yaml이
# 그것을 못박는다. package-lock.json은 없으므로 npm install을 하면 락파일이
# 보장하는 것과 다른 트리가 만들어진다. 게다가 npm은 pnpm이 만든 심볼릭 링크
# 구조를 읽지 못해 "Cannot read properties of null"로 죽는다.
if command -v pnpm >/dev/null 2>&1; then
  ok "pnpm — $(pnpm --version)"
else
  warn "pnpm 없음 — corepack으로 설치한다"
  corepack enable >/dev/null 2>&1 && corepack prepare pnpm@11.18.0 --activate >/dev/null 2>&1
  if command -v pnpm >/dev/null 2>&1; then
    ok "pnpm 설치 — $(pnpm --version)"
  else
    bad "pnpm 설치 실패 — npm i -g pnpm 또는 brew install pnpm"
    MISSING=1
  fi
fi
if command -v docker >/dev/null 2>&1; then
  ok "docker — 배포 전 컨테이너 검증에 쓴다 (08 가이드 §6-4)"
else
  warn "docker 없음 — 배포 검증만 못 한다. 개발에는 지장 없다"
fi

if [ "$MISSING" = 1 ]; then
  bad "필수 도구가 없어 중단한다"
  exit 1
fi

# ── 2. 백엔드 의존성 ─────────────────────────────────────────────────
head_ "2. 백엔드 의존성"
cd "$ROOT/backend"
[ -d .venv ] || python3.12 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
if ./.venv/bin/pip install -q -e ".[dev]"; then
  ok "설치 완료 (개발 의존성 포함)"
else
  bad "설치 실패"
  exit 1
fi
if ./.venv/bin/python -c "import chromadb" 2>/dev/null; then
  ok "chromadb 있음 — RAG를 켤 수 있다"
else
  warn "chromadb 없음 — RAG 없이 동작한다. 쓰려면: .venv/bin/pip install -e '.[rag]'"
fi

# ── 3. 프론트엔드 의존성 ─────────────────────────────────────────────
head_ "3. 프론트엔드 의존성"
cd "$ROOT/frontend"
# --frozen-lockfile: 락파일과 package.json이 어긋나면 조용히 고치지 말고 실패시킨다.
# 기기마다 다른 버전이 깔리는 것이 재현 안 되는 버그의 흔한 출처다.
if pnpm install --frozen-lockfile --silent; then
  ok "pnpm 패키지 설치 (락파일 고정)"
else
  bad "pnpm install 실패 — 락파일과 package.json이 어긋났을 수 있다"
  exit 1
fi
if pnpm exec playwright install chromium >/dev/null 2>&1; then
  ok "Playwright 브라우저"
else
  warn "Playwright 브라우저 설치 실패 — 수동: pnpm exec playwright install chromium"
fi

# ── 4. 로컬 테스트 DB ────────────────────────────────────────────────
head_ "4. 로컬 테스트 DB (저장소 계약 테스트용)"
TEST_DB="${TEST_DATABASE_URL:-postgresql://127.0.0.1:5432/regradar_test}"
if psql "$TEST_DB" -c "SELECT 1" >/dev/null 2>&1; then
  ok "regradar_test 접속 가능"
elif createdb regradar_test 2>/dev/null; then
  ok "regradar_test 생성"
else
  warn "생성 실패 — Postgres가 떠 있는지 확인: brew services start postgresql@16"
fi

cd "$ROOT/backend"
if psql "$TEST_DB" -c "SELECT 1" >/dev/null 2>&1; then
  if DATABASE_URL="$TEST_DB" ./.venv/bin/python scripts/migrate.py >/dev/null 2>&1; then
    ok "마이그레이션 적용"
  else
    warn "마이그레이션 실패 — DATABASE_URL=$TEST_DB .venv/bin/python scripts/migrate.py 로 확인"
  fi
fi

# ── 5. 설정 파일 (비밀값은 사람이 옮긴다) ────────────────────────────
head_ "5. 설정 파일"
check_env() {
  local path="$1" example="$2" label="$3"
  if [ -f "$path" ]; then
    ok "$label 있음"
  else
    if [ -f "$example" ]; then
      cp "$example" "$path"
      warn "$label 없어 예시로 만들었다 — 값을 채워야 한다"
    else
      bad "$label 없고 예시 파일도 없다"
    fi
    MISSING=1
  fi
}
check_env "$ROOT/backend/.env"            "$ROOT/backend/.env.example"      "backend/.env"
check_env "$ROOT/frontend/.env.local"     "$ROOT/frontend/.env.example"     "frontend/.env.local"
check_env "$ROOT/frontend/.env.e2e.local" "$ROOT/frontend/.env.e2e.example" "frontend/.env.e2e.local"

# ── 6. 확인 ──────────────────────────────────────────────────────────
head_ "6. 확인"
cd "$ROOT/backend"
./.venv/bin/python -m pytest -q 2>&1 | tail -1

if [ "$MISSING" = 1 ]; then
  cat <<'MSG'

──────────────────────────────────────────────────────────────────────
아직 남았다: 비밀값은 저장소에 없다

backend/.env
  DATABASE_URL     Supabase → Project Settings → Database → Connection string
                   **Session pooler(포트 5432)** 를 쓴다. Direct는 IPv6라 Render에서 실패한다
  OPENAI_API_KEY   platform.openai.com → API keys
  LAW_API_OC       open.law.go.kr 가입 아이디
  SUPABASE_URL     Supabase → Project Settings → API
  AUTH_MODE=supabase, STORAGE=postgres 로 둔다

frontend/.env.local
  NEXT_PUBLIC_API_BASE_URL              http://127.0.0.1:8000/api/v1
  NEXT_PUBLIC_SUPABASE_URL              (backend와 같은 값)
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY  Supabase → API → publishable key
  ※ 셋 다 브라우저에 노출되는 공개값이다

frontend/.env.e2e.local
  E2E_PASSWORD     E2E 데모 계정 비밀번호

가장 빠른 길은 기존 기기에서 이 세 파일을 그대로 옮기는 것이다
(1Password·AirDrop 등). 채팅·이슈·커밋에 붙여넣지 않는다.
──────────────────────────────────────────────────────────────────────
MSG
else
  cat <<'MSG'

준비 끝. 두 개를 띄운다.

  cd backend  && .venv/bin/python -m uvicorn app.main:app --port 8000
  cd frontend && pnpm dev

확인:
  curl -s localhost:8000/api/v1/health | python3 -m json.tool
  cd frontend && pnpm e2e
MSG
fi
