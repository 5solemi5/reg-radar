"""AI 실행 추적 리포트 (NFR-009).

무엇이 느리고 무엇이 비싼지를 본다.

    .venv/bin/python scripts/trace_report.py            # 최근 분석 10건
    .venv/bin/python scripts/trace_report.py --chains   # 체인별 집계
    .venv/bin/python scripts/trace_report.py --failures # 실패한 호출만
"""

import asyncio
import sys

import asyncpg

from app.core.config import get_settings


async def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("✗ DATABASE_URL이 필요합니다 (trace는 Postgres에 저장됩니다).")
        return 1

    connection = await asyncpg.connect(settings.database_url, timeout=25)
    try:
        total = await connection.fetchval("SELECT count(*) FROM ai_traces")
        if not total:
            print("기록된 trace가 없습니다. 분석을 한 번 실행해 보세요.")
            return 0
        print(f"▶ 총 {total:,}건의 체인 호출 기록\n")

        if "--chains" in sys.argv:
            print("=== 체인별 집계 ===")
            rows = await connection.fetch(
                """
                SELECT chain, model,
                       count(*) AS calls,
                       count(*) FILTER (WHERE NOT ok) AS failures,
                       avg(latency_ms)::int AS avg_ms,
                       max(latency_ms) AS max_ms,
                       sum(input_tokens) AS in_tok,
                       sum(output_tokens) AS out_tok
                FROM ai_traces GROUP BY chain, model ORDER BY sum(input_tokens) DESC
                """
            )
            print(f"{'체인':<28}{'모델':<10}{'호출':>6}{'실패':>5}"
                  f"{'평균ms':>8}{'최대ms':>8}{'입력토큰':>10}{'출력토큰':>9}")
            for r in rows:
                print(f"{r['chain']:<28}{r['model']:<10}{r['calls']:>6}{r['failures']:>5}"
                      f"{r['avg_ms']:>8,}{r['max_ms']:>8,}"
                      f"{r['in_tok']:>10,}{r['out_tok']:>9,}")
            return 0

        if "--failures" in sys.argv:
            rows = await connection.fetch(
                """
                SELECT created_at, chain, model, latency_ms, article_no, error
                FROM ai_traces WHERE NOT ok ORDER BY created_at DESC LIMIT 20
                """
            )
            if not rows:
                print("실패한 호출이 없습니다.")
                return 0
            print("=== 실패한 호출 (최근 20건) ===")
            for r in rows:
                print(f"  {r['created_at']:%m-%d %H:%M}  {r['chain']:<28}"
                      f"{r['article_no'] or '-':<12}{r['latency_ms']:>7,}ms")
                print(f"      {(r['error'] or '')[:110]}")
            return 0

        print("=== 최근 분석 ===")
        rows = await connection.fetch(
            """
            SELECT a.created_at, a.status::text AS status, a.law_query,
                   a.laws_examined, a.articles_changed,
                   coalesce(s.chain_calls, 0) AS calls,
                   coalesce(s.failures, 0) AS failures,
                   coalesce(s.total_tokens, 0) AS tokens,
                   coalesce(s.total_latency_ms, 0) AS latency
            FROM analyses a
            LEFT JOIN analysis_trace_summary s ON s.analysis_id = a.analysis_id
            ORDER BY a.created_at DESC LIMIT 10
            """
        )
        print(f"{'시각':<13}{'상태':<11}{'대상':<16}{'조문':>5}"
              f"{'호출':>6}{'실패':>5}{'토큰':>9}{'소요':>9}")
        for r in rows:
            print(f"{r['created_at']:%m-%d %H:%M}  {r['status']:<11}"
                  f"{(r['law_query'] or '기간')[:15]:<16}{r['articles_changed']:>5}"
                  f"{r['calls']:>6}{r['failures']:>5}"
                  f"{r['tokens']:>9,}{r['latency'] / 1000:>8.1f}s")

        cost = await connection.fetchrow(
            "SELECT sum(input_tokens) AS i, sum(output_tokens) AS o FROM ai_traces"
        )
        print(f"\n누적 토큰: 입력 {cost['i']:,} / 출력 {cost['o']:,}")
        print("(비용은 모델 단가에 따라 다르므로 여기서 계산하지 않는다)")
        return 0
    finally:
        await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
