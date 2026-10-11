"""운영 지표 (R4) — 호출 비용, 프롬프트 버전, Validator 거부·재생성이 trace에 남는다."""

import pytest

from app.ai.chains.base import ChainTrace
from app.core.pricing import cost_usd, prompt_version
from app.repositories.traces import (
    InMemoryTraceRepository,
    PostgresTraceRepository,
    TraceRecord,
)
from tests.test_analysis_pipeline import APPLICABLE_OUT, FAKE_CITATION, SequenceRunner, make_packet
from tests.test_repositories import database  # noqa: F401


def test_단가표로_비용을_계산하고_모르는_모델은_0이_아니라_None():
    assert cost_usd("gpt-4o", 1_000_000, 100_000) == 3.5
    assert cost_usd("rules", 0, 0) is None
    assert ChainTrace("C4", "gpt-4o-mini", 10, True, input_tokens=2000).cost_usd == 0.0003


def test_프롬프트_버전은_체인이_쓰는_파일을_따른다():
    assert prompt_version("C4_applicability_mapping") == prompt_version("C3_x")
    assert prompt_version("C7_policy_impact") != prompt_version("C4_applicability_mapping")
    assert len(prompt_version("C8_policy_draft")) == 12


async def test_재생성과_Validator_거부가_trace에_남는다():
    from app.services.analysis_service import analyze_article

    runner = SequenceRunner([FAKE_CITATION, APPLICABLE_OUT])
    await analyze_article(runner, make_packet(employee_count=80), max_retries=2)
    rules = [t for t in runner.traces if t.model == "rules"]
    assert [(t.ok, t.attempt) for t in rules] == [(False, 0), (True, 1)]
    assert "인용" in rules[0].error
    assert all(t.prompt_version for t in runner.traces)


def _records():
    def rec(chain, model, ok=True, attempt=0, tin=0, tout=0, error=None):
        t = ChainTrace(chain, model, 5, ok, error=error, input_tokens=tin, output_tokens=tout,
                       attempt=attempt, prompt_version=prompt_version(chain))
        return TraceRecord.of(t, trace_id="00000000-0000-0000-0000-000000000001",
                              analysis_id=None, user_id="u1")
    return [
        rec("C4", "gpt-4o", tin=1_000_000),
        rec("C6_validator", "rules", ok=False, error="인용 탈락"),
        rec("C4", "gpt-4o", attempt=1, tout=100_000),
        rec("C6_validator", "rules", attempt=1),
    ]


async def test_집계는_LLM_호출과_규칙_검증을_가른다():
    repo = InMemoryTraceRepository()
    records = _records()
    for r in records:
        r.analysis_id = "a1"
    await repo.save_many(records)
    s = await repo.summarize("a1", "u1")
    assert (s.chain_calls, s.failures, s.validator_rejects, s.regenerations) == (2, 0, 1, 1)
    assert s.cost_usd == 3.5


async def test_Postgres에_새_열이_저장된다(database):  # noqa: F811
    await database.execute("TRUNCATE ai_traces")
    await PostgresTraceRepository(database).save_many(_records())
    rows = await database.fetch(
        "SELECT chain, cost_usd, prompt_version, attempt FROM ai_traces ORDER BY attempt, chain"
    )
    if not rows:
        pytest.fail("trace가 저장되지 않았다 (마이그레이션 009 적용 확인)")
    assert [r["attempt"] for r in rows] == [0, 0, 1, 1]
    assert {float(r["cost_usd"]) for r in rows if r["cost_usd"] is not None} == {2.5, 1.0}
    assert all(r["prompt_version"] for r in rows)


async def test_요청마다_지연을_헤더와_로그로_남긴다(client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="app.main"):
        r = await client.get("/api/v1/results/some-id")
    assert r.headers["Server-Timing"].startswith("app;dur=")
    line = next(m for m in caplog.messages if m.startswith("request "))
    assert "route=/results/{result_id}" in line and "some-id" not in line
