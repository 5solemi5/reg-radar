"""재생 기반 평가 회귀 검사 (문서 12 §3-4).

녹화된 LLM 응답(cassette)과 고정 법령 snapshot으로 데이터셋을 다시 돌려,
저장된 기준과 **정확히** 같은지 본다.
키도 네트워크도 필요 없다. CI에서 돈다.

    # 기준 만들기 (녹화가 있어야 한다: run_eval.py --offline --record)
    .venv/bin/python scripts/check_eval_regression.py \
        --dataset evaluation/datasets/holdout_v3.json --update
    # 검사
    .venv/bin/python scripts/check_eval_regression.py --dataset evaluation/datasets/holdout_v3.json

실패하는 경우
- 판정·지표가 기준과 다르다 → 코드 변경이 판정을 바꿨다.
  의도한 변경이면 --update로 기준을 갱신하고 이유를 커밋에 남긴다.
- cassette에 없는 호출 → 프롬프트·스키마·입력이 바뀌었다. 녹화를 새로 하고(과금) 기준을 갱신한다.
- Q1 노출 정확도가 1.0이 아니다 → Validator가 원문에 없는 인용을 노출했다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.ai.cassette import Cassette, CassetteMode
from app.core.config import get_settings
from evaluation.runner import run_dataset

ROOT = Path(__file__).resolve().parent.parent
CASSETTES = ROOT / "evaluation" / "cassettes"
BASELINES = ROOT / "evaluation" / "baselines"
VOLATILE = {"failures"}  # 객체 목록 — 케이스별 판정은 따로 비교한다


def snapshot_of(metrics, outcomes) -> dict:
    return {
        "metrics": {k: v for k, v in vars(metrics).items() if k not in VOLATILE},
        "cases": {
            o.case_id: {
                "predicted": o.predicted.value if o.predicted else None,
                "status": o.status.value if o.status else None,
                "action_grade": o.action_grade.value if o.action_grade else None,
                "cited_verified": o.cited_verified,
                "cited_total": o.cited_total,
                "displayed_verified": o.displayed_verified,
                "displayed_total": o.displayed_total,
                "error": o.error,
            }
            for o in outcomes
        },
    }


def diff(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            out += diff(a.get(k), b.get(k), f"{path}.{k}" if path else str(k))
        return out
    return [] if a == b else [f"{path}: 기준 {a!r} → 지금 {b!r}"]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--update", action="store_true", help="현재 재생 결과로 기준을 덮어쓴다")
    args = ap.parse_args()

    settings = get_settings()
    if args.model:
        settings = settings.model_copy(update={"llm_model": args.model})
    stem = f"{Path(args.dataset).stem}__{settings.llm_model}"
    cassette = Cassette(CASSETTES / f"{stem}.jsonl", CassetteMode.REPLAY, settings.llm_model)

    metrics, outcomes = await run_dataset(
        args.dataset, settings=settings, offline=True, concurrency=4, cassette=cassette
    )
    current = snapshot_of(metrics, outcomes)
    misses = [o.case_id for o in outcomes if o.error and "녹화에 없는 호출" in o.error]
    if misses:
        print(f"✗ cassette에 없는 호출: {misses} — 프롬프트·스키마·입력이 녹화 이후 바뀌었다.")
        return 1
    q1 = metrics.q1_displayed_citation_accuracy
    if q1 is not None and q1 != 1.0:
        print(f"✗ Q1 노출 인용 정확도 {q1:.3f} — Validator가 원문에 없는 인용을 노출했다.")
        return 1

    baseline_path = BASELINES / f"{stem}.json"
    if args.update:
        BASELINES.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"✓ 기준 갱신: {baseline_path.relative_to(ROOT)}")
        return 0
    if not baseline_path.exists():
        print(f"✗ 기준이 없다: {baseline_path.relative_to(ROOT)} (--update로 만든다)")
        return 1
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    changes = diff(baseline, json.loads(json.dumps(current)))
    if changes:
        print("✗ 기준과 다르다:")
        for c in changes:
            print("   ", c)
        return 1
    print(f"✓ 기준과 같다: {stem} · 케이스 {len(outcomes)}건 · cassette {cassette.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
