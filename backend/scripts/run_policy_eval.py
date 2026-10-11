"""사내 규정 영향 평가 CLI (문서 12 §4).

    .venv/bin/python scripts/run_policy_eval.py --split dev --record   # 실제 호출·녹화 (과금)
    .venv/bin/python scripts/run_policy_eval.py --split dev --replay   # 재생 — 키·과금 없음
    .venv/bin/python scripts/run_policy_eval.py --split sealed --record --save  # 봉인셋: 한 번만

법령 원문은 평가용 snapshot 캐시만 쓴다(법제처 호출 없음).
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from app.ai.cassette import Cassette, CassetteMode
from app.core.config import get_settings
from evaluation.policy_impact import render, run
from evaluation.provenance import PRICE_PER_MTOK, git_state, sha256_file

BACKEND = Path(__file__).resolve().parent.parent
DATASET = BACKEND / "evaluation" / "datasets" / "policy_impact_v3.json"
RESULTS_DIR = BACKEND / "evaluation" / "results"
CASSETTE_DIR = BACKEND / "evaluation" / "cassettes"
POLICY_FILES = [BACKEND / "app" / "policies" / "prompts.py",
                BACKEND / "app" / "policies" / "corpus" / "virtual_card_co.json",
                BACKEND / "app" / "policies" / "corpus" / "virtual_card_co_v2.json",
                BACKEND / "app" / "policies" / "corpus" / "virtual_card_co_v3.json",
                BACKEND / "app" / "policies" / "corpus" / "virtual_card_co_v4.json"]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--split", choices=["dev", "sealed", "all"], default="dev")
    parser.add_argument("--model", default=None)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--save", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--replay", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if args.model:
        settings = settings.model_copy(update={"llm_model": args.model})
    if not args.replay and not settings.llm_enabled:
        print("✗ OPENAI_API_KEY가 없습니다.")
        return 1

    cassette = None
    if args.record or args.replay:
        path = CASSETTE_DIR / f"{Path(args.dataset).stem}__{settings.llm_model}.jsonl"
        cassette = Cassette(path, CassetteMode.RECORD if args.record else CassetteMode.REPLAY,
                            settings.llm_model)

    metrics, results = await run(Path(args.dataset), split=args.split, settings=settings,
                                 cassette=cassette, concurrency=args.concurrency)
    price = PRICE_PER_MTOK.get(settings.llm_model)
    if price:
        metrics["cost_usd_estimate"] = round(
            metrics["input_tokens"] / 1e6 * price["input"]
            + metrics["output_tokens"] / 1e6 * price["output"], 4
        )
    provenance = {
        "dataset_sha256": sha256_file(Path(args.dataset)),
        "policy_files_sha256": {p.name: sha256_file(p)[:12] for p in POLICY_FILES},
        "split": args.split,
        "model": settings.llm_model,
        "git": git_state(),
        "cassette": cassette.summary() if cassette else {"mode": "off"},
    }
    print(f"▶ 출처: {json.dumps(provenance, ensure_ascii=False)}\n")
    report = render(metrics, results)
    print(report)
    print(f"\n▶ 지표: {json.dumps(metrics, ensure_ascii=False)}")

    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        base = RESULTS_DIR / f"{stamp}_policy_impact_{args.split}_{settings.llm_model}"
        base.with_suffix(".txt").write_text(report, encoding="utf-8")
        base.with_suffix(".json").write_text(json.dumps({
            "provenance": provenance, "metrics": metrics,
            "cases": [r.__dict__ for r in results],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ 저장: {base}.txt / .json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
