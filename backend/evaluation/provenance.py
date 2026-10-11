"""평가 결과의 출처 기록 (문서 12 §3-2).

결과 숫자만 남기면 나중에 "어떤 데이터셋·코드·프롬프트로 낸 숫자인가"를 답할 수 없다.
같은 숫자를 다시 만들려면 아래가 모두 같아야 한다.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from evaluation.metrics import CaseOutcome

BACKEND = Path(__file__).resolve().parent.parent
PROMPTS = BACKEND / "app" / "ai" / "prompts.py"

# 단가표는 앱과 같은 것을 쓴다(app/core/pricing.py). 결과 파일에 함께 기록한다.
from app.core.pricing import PRICE_PER_MTOK  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prompt_version() -> str:
    """프롬프트 원문 해시. 프롬프트를 한 글자라도 바꾸면 달라진다."""
    return sha256_file(PROMPTS)[:12]


def git_state() -> dict:
    def run(*args):
        try:
            return subprocess.run(
                ["git", *args], cwd=BACKEND, capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except Exception:
            return ""

    return {
        "commit": run("rev-parse", "--short", "HEAD") or None,
        "dirty": bool(run("status", "--porcelain")),
    }


def usage_and_cost(outcomes: list[CaseOutcome], model: str) -> dict:
    tin = sum(o.input_tokens for o in outcomes)
    tout = sum(o.output_tokens for o in outcomes)
    price = PRICE_PER_MTOK.get(model)
    cost = (
        None
        if price is None
        else round(tin / 1e6 * price["input"] + tout / 1e6 * price["output"], 4)
    )
    return {
        "input_tokens": tin,
        "output_tokens": tout,
        "cost_usd_estimate": cost,
        "price_per_mtok_assumed": price,
    }
