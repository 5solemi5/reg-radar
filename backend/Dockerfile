# 규제 변화 AI 도우미 — 백엔드
#
# Railway·Render·Fly.io·Cloud Run 등 상시 실행 호스트용이다. 서버리스가 아닌
# 이유는 분석이 202 응답 후 백그라운드에서 수십 초 돌기 때문이다. 서버리스는
# 응답을 보내는 순간 함수가 종료되므로 그 작업이 잘린다 (01 기획서 §12).

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성을 먼저 설치해 코드 변경 시 레이어 캐시를 재사용한다.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY migrations ./migrations
COPY evaluation ./evaluation
COPY scripts ./scripts

# 루트로 실행하지 않는다.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# 호스트가 주는 포트를 쓴다. 고정하면 플랫폼마다 다시 고쳐야 한다.
ENV PORT=8000
EXPOSE 8000

# 헬스 체크는 외부 의존성을 호출하지 않는다 — 설정 상태만 본다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; \
urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/api/v1/health\").read()"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
