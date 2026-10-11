"""평가 재현성 (문서 12 §3) — LLM 응답 녹화·재생, Q1 노출 정확도 실측.

키·네트워크 없이 돈다. 가짜 게이트웨이가 호출 횟수를 센다.
"""

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.ai.cassette import Cassette, CassetteMiss, CassetteMode, call_key
from app.ai.chains.base import ChainExecutionError, ChainRunner
from app.domain.enums import Applicability
from evaluation.metrics import CaseOutcome, compute
from evaluation.runner import independent_contains


class Out(BaseModel):
    answer: str
    cited_spans: list[str] = []


class OutV2(BaseModel):
    answer: str
    cited_spans: list[str] = []
    confidence: float = 0.0


class _Raw:
    usage_metadata = {"input_tokens": 120, "output_tokens": 30}


class FakeGateway:
    """structured_with_usage(schema).ainvoke(messages)만 흉내 낸다."""

    model_name = "fake-model"

    def __init__(self):
        self.calls = 0

    def structured_with_usage(self, schema):
        gw = self

        class _Runnable:
            async def ainvoke(self, messages):
                gw.calls += 1
                return {
                    "raw": _Raw(),
                    "parsed": schema(answer=f"응답{gw.calls}"),
                    "parsing_error": None,
                }

        return _Runnable()


class ExplodingGateway:
    model_name = "fake-model"

    def structured_with_usage(self, schema):
        raise AssertionError("재생 모드에서 LLM을 불렀다")


def cassette(tmp_path: Path, mode: CassetteMode) -> Cassette:
    return Cassette(tmp_path / "c.jsonl", mode, "gpt-4o")


async def test_녹화한_응답을_재생하면_LLM을_부르지_않고_같은_결과(tmp_path):
    gw = FakeGateway()
    rec = cassette(tmp_path, CassetteMode.RECORD)
    first = await ChainRunner(llm=gw, cassette=rec).invoke(chain="C4", prompt="조문 A", schema=Out)
    assert gw.calls == 1 and rec.recorded == 1

    play = cassette(tmp_path, CassetteMode.REPLAY)
    runner = ChainRunner(llm=ExplodingGateway(), cassette=play)
    again = await runner.invoke(chain="C4", prompt="조문 A", schema=Out)
    assert again == first
    assert play.hits == 1
    assert runner.traces[0].input_tokens == 120  # 녹화 당시 토큰 수가 trace로 이어진다


async def test_프롬프트가_한_글자라도_바뀌면_재생이_실패한다(tmp_path):
    await ChainRunner(llm=FakeGateway(), cassette=cassette(tmp_path, CassetteMode.RECORD)).invoke(
        chain="C4", prompt="조문 A", schema=Out
    )
    play = cassette(tmp_path, CassetteMode.REPLAY)
    with pytest.raises(CassetteMiss):
        await ChainRunner(llm=ExplodingGateway(), cassette=play).invoke(
            chain="C4", prompt="조문 A.", schema=Out
        )
    assert play.misses == 1


def test_스키마가_바뀌면_키가_바뀐다():
    k1 = call_key(chain="C4", model="gpt-4o", system="s", prompt="p", schema=Out)
    k2 = call_key(chain="C4", model="gpt-4o", system="s", prompt="p", schema=OutV2)
    k3 = call_key(chain="C4", model="gpt-4o-mini", system="s", prompt="p", schema=Out)
    assert len({k1, k2, k3}) == 3


def test_녹화가_없으면_재생을_시작하지_않는다(tmp_path):
    with pytest.raises(CassetteMiss):
        cassette(tmp_path, CassetteMode.REPLAY)


async def test_같은_호출은_한_번만_녹화한다(tmp_path):
    gw = FakeGateway()
    rec = cassette(tmp_path, CassetteMode.RECORD)
    runner = ChainRunner(llm=gw, cassette=rec)
    await runner.invoke(chain="C3", prompt="같은 입력", schema=Out)
    await runner.invoke(chain="C3", prompt="같은 입력", schema=Out)
    assert rec.recorded == 1
    assert len((tmp_path / "c.jsonl").read_text(encoding="utf-8").splitlines()) == 1


async def test_cassette가_없으면_지금과_똑같이_동작한다():
    gw = FakeGateway()
    out = await ChainRunner(llm=gw).invoke(chain="C3", prompt="x", schema=Out)
    assert out.answer == "응답1" and gw.calls == 1


def test_운영_분석_경로는_cassette를_쓰지_않는다():
    src = (Path(__file__).parent.parent / "app" / "services" / "analysis_runner.py").read_text(
        encoding="utf-8"
    )
    assert "cassette" not in src.lower()


# ── Q1 노출 정확도: 1.0을 적는 대신 실제로 잰다 ─────────────────────────


def test_독립_대조는_공백_차이를_허용하고_지어낸_문장은_거부한다():
    original = "사업주는 근로자에게\n  연차 유급휴가를 주어야 한다."
    assert independent_contains("근로자에게 연차 유급휴가를", original)
    assert not independent_contains("근로자에게 성과급을", original)
    assert not independent_contains("   ", original)


def _outcome(displayed_total, displayed_verified):
    return CaseOutcome(
        case_id="X",
        law_name="법",
        article_no="제1조",
        profile="p",
        gold=Applicability.APPLICABLE,
        predicted=Applicability.APPLICABLE,
        status=None,
        action_grade=None,
        displayed_total=displayed_total,
        displayed_verified=displayed_verified,
    )


def test_Q1_노출_정확도는_측정값이다():
    m = compute([_outcome(4, 4), _outcome(2, 1)])
    assert m.q1_displayed_citation_accuracy == pytest.approx(
        5 / 6
    )  # Validator 구멍이 있으면 1.0 미만이 된다
    assert (
        compute([_outcome(0, 0)]).q1_displayed_citation_accuracy is None
    )  # 노출 인용이 없으면 측정 불가


class SlowGateway(FakeGateway):
    """응답 전에 이벤트 루프를 양보한다 — 동시 호출이 겹치게 만든다."""

    def structured_with_usage(self, schema):
        inner = super().structured_with_usage(schema)

        class _Runnable:
            async def ainvoke(self, messages):
                await asyncio.sleep(0.01)
                return await inner.ainvoke(messages)

        return _Runnable()


async def test_녹화_중_같은_호출이_동시에_오면_한_번만_부르고_결과를_나눈다(tmp_path):
    # 같은 조문의 C3를 두 케이스가 동시에 부르던 실제 버그(2026-10-11): LLM이 두 번 불려 서로
    # 다른 답이 나오고, 녹화에는 하나만 남아 그 뒤 C4 재생이 어긋났다.
    gw = SlowGateway()
    rec = cassette(tmp_path, CassetteMode.RECORD)
    runners = [ChainRunner(llm=gw, cassette=rec) for _ in range(3)]
    outs = await asyncio.gather(
        *(r.invoke(chain="C3", prompt="같은 조문", schema=Out) for r in runners)
    )
    assert gw.calls == 1
    assert {o.answer for o in outs} == {"응답1"}
    assert rec.recorded == 1


async def test_녹화된_키는_다시_녹화할_때_LLM을_부르지_않는다(tmp_path):
    await ChainRunner(llm=FakeGateway(), cassette=cassette(tmp_path, CassetteMode.RECORD)).invoke(
        chain="C3", prompt="조문 A", schema=Out
    )
    again = cassette(tmp_path, CassetteMode.RECORD)  # 이어서 녹화 — 빠진 호출만 과금된다
    out = await ChainRunner(llm=ExplodingGateway(), cassette=again).invoke(
        chain="C3", prompt="조문 A", schema=Out
    )
    assert out.answer == "응답1" and again.recorded == 0


class FailingGateway(FakeGateway):
    def structured_with_usage(self, schema):
        class _Runnable:
            async def ainvoke(self, messages):
                raise RuntimeError("rate limited")

        return _Runnable()


async def test_녹화_때_실패한_호출은_재생에서도_같은_실패다(tmp_path):
    rec = cassette(tmp_path, CassetteMode.RECORD)
    with pytest.raises(ChainExecutionError):
        await ChainRunner(llm=FailingGateway(), cassette=rec).invoke(
            chain="C4", prompt="조문 B", schema=Out
        )
    play = cassette(tmp_path, CassetteMode.REPLAY)
    runner = ChainRunner(llm=ExplodingGateway(), cassette=play)
    with pytest.raises(ChainExecutionError, match="rate limited"):
        await runner.invoke(chain="C4", prompt="조문 B", schema=Out)
    assert runner.traces[0].ok is False
