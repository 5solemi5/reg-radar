"""모델 단가와 프롬프트 버전 (R4 운영 지표, 문서 12 §2).

단가는 가정값이다. 공급자 단가가 바뀌면 여기만 고친다. 평가 결과(evaluation/provenance.py)와
운영 trace가 같은 표를 쓴다 — 둘이 다르면 "평가 때 얼마"와 "운영에서 얼마"를 비교할 수 없다.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

# 1M 토큰당 USD
PRICE_PER_MTOK: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """단가표에 없는 모델이면 None — 0으로 두면 '공짜'로 읽힌다."""
    price = PRICE_PER_MTOK.get(model)
    if price is None:
        return None
    return round(input_tokens / 1e6 * price["input"] + output_tokens / 1e6 * price["output"], 6)


_APP = Path(__file__).resolve().parent.parent
_PROMPT_FILES = {
    "policy": _APP / "policies" / "prompts.py",
    "analysis": _APP / "ai" / "prompts.py",
}


@cache
def _file_version(kind: str) -> str:
    return hashlib.sha256(_PROMPT_FILES[kind].read_bytes()).hexdigest()[:12]


def prompt_version(chain: str) -> str:
    """체인이 쓰는 프롬프트 파일의 해시 앞 12자리. 프롬프트를 한 글자만 바꿔도 달라진다."""
    kind = "policy" if chain.startswith(("C7", "C8")) else "analysis"
    return _file_version(kind)
