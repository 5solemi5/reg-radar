"""사내 규정 영향 평가 회귀 — 녹화된 C7·C8 응답을 재생해 기준 지표와 정확히 비교한다.

프롬프트·스키마·검색·검증 규칙을 바꾸면 여기서 깨진다. 의도한 변경이면 dev를 다시 녹화하고
기준(evaluation/baselines/policy_impact_v3__gpt-4o.json)을 갱신한다.
sealed는 이미 소진됐다(v4에서 잰다).
v1·v2는 프롬프트가 바뀌어 재생 기준에서 은퇴했다(결과 파일만 남는다).
"""

import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
CASSETTE = BACKEND / "evaluation" / "cassettes" / "policy_impact_v3__gpt-4o.jsonl"
BASELINE = BACKEND / "evaluation" / "baselines" / "policy_impact_v3__gpt-4o.json"
SNAPSHOTS = BACKEND / "evaluation" / "ci" / "snapshots"


@pytest.mark.parametrize("split", ["dev", "sealed"])
async def test_재생_지표가_기준과_같다(split, monkeypatch):
    from app.ai.cassette import Cassette, CassetteMode
    from app.core.config import get_settings
    from evaluation import policy_impact

    monkeypatch.setattr(policy_impact, "EVAL_SNAPSHOT_DIR", SNAPSHOTS)
    settings = get_settings().model_copy(update={"llm_model": "gpt-4o"})
    cassette = Cassette(CASSETTE, CassetteMode.REPLAY, "gpt-4o")
    metrics, _ = await policy_impact.run(
        BACKEND / "evaluation" / "datasets" / "policy_impact_v3.json",
        split=split, settings=settings, cassette=cassette,
    )
    assert cassette.misses == 0
    assert metrics == json.loads(BASELINE.read_text(encoding="utf-8"))[split]
