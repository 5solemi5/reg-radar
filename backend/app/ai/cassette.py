"""LLM 응답 녹화·재생 — 평가 전용 (문서 12 §3-1).

평가를 돌릴 때마다 실제 LLM을 부르면 돈이 들고(케이스당 2~3회 호출) 숫자가 흔들린다
(temperature 0이어도 비결정). 한 번 녹화한 응답으로 같은 입력을 다시 돌리면
**같은 숫자**가 나와야 회귀를 잡을 수 있다.

- 키 = sha256(체인 이름, 모델, 시스템·사용자 프롬프트, 출력 스키마의 JSON 스키마).
  프롬프트나 스키마가 한 글자라도 바뀌면 키가 바뀐다 → 재생이 실패한다 → 다시 녹화하라는 신호다.
- 재생에서 키가 없으면 **실패한다.** 조용히 실제 호출로 넘어가지 않는다.
- 평가 데이터셋 전용이다. 운영 분석 경로(`AnalysisRunner`)는 cassette를 받지 않는다.
  사용자 데이터가 파일에 남지 않게 하려는 것이다
  (관측성의 "프롬프트·응답 원문 미저장" 정책과 같은 이유).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel


class CassetteMode(StrEnum):
    OFF = "off"
    RECORD = "record"
    REPLAY = "replay"


class CassetteMiss(RuntimeError):
    """재생 모드에서 녹화되지 않은 호출을 만났다 — 프롬프트·스키마·입력이 녹화 이후 바뀌었다."""


def call_key(*, chain: str, model: str, system: str, prompt: str, schema: type[BaseModel]) -> str:
    payload = json.dumps(
        {
            "chain": chain,
            "model": model,
            "system": system,
            "prompt": prompt,
            "schema": schema.model_json_schema(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Recorded:
    parsed: dict | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    error: str | None = None  # 녹화 때 실패한 호출. 재생에서도 같은 실패를 재현한다


@dataclass
class Cassette:
    path: Path
    mode: CassetteMode
    model: str
    _entries: dict[str, Recorded] = field(default_factory=dict, repr=False)
    hits: int = 0
    misses: int = 0
    recorded: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # key → asyncio.Future. 녹화 중 같은 키를 동시에 부르면 뒤쪽은 앞쪽 결과를 기다린다
    _inflight: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.mode is not CassetteMode.OFF and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._entries[row["key"]] = Recorded(
                        row["parsed"],
                        row["input_tokens"],
                        row["output_tokens"],
                        row["latency_ms"],
                        row.get("error"),
                    )
        if self.mode is CassetteMode.REPLAY and not self._entries:
            raise CassetteMiss(f"재생할 녹화가 없다: {self.path}")

    @property
    def active(self) -> bool:
        return self.mode is not CassetteMode.OFF

    def lookup(self, key: str) -> Recorded:
        rec = self._entries.get(key)
        if rec is None:
            self.misses += 1
            raise CassetteMiss(
                f"녹화에 없는 호출(key={key[:12]}…). 프롬프트·스키마·입력이 바뀌었다면 "
                "--record로 다시 녹화하고 기준을 갱신한다."
            )
        self.hits += 1
        return rec

    # ── 녹화 모드 ────────────────────────────────────────────────────
    # 같은 키(같은 프롬프트)는 한 번만 실제로 부른다. LLM은 temperature 0에서도
    # 같은 입력에 다른 답을 줄 수 있다. 같은 조문의 C3를 두 케이스가 따로 부르면
    # 서로 다른 C3 답이 각자의 C4 프롬프트로 이어지는데, 녹화본에는 키당 하나만 남아
    # 재생이 어긋난다(2026-10-11 실제로 발생).
    def peek(self, key: str) -> Recorded | None:
        return self._entries.get(key)

    def claim(self, key: str) -> asyncio.Future | None:
        """처음 부르는 쪽이면 None(직접 호출한다). 이미 부르는 중이면 그 결과를 기다릴 Future."""
        fut = self._inflight.get(key)
        if fut is not None:
            return fut
        self._inflight[key] = asyncio.get_running_loop().create_future()
        return None

    def resolve(self, key: str, rec: Recorded) -> None:
        fut = self._inflight.pop(key, None)
        if fut is not None and not fut.done():
            fut.set_result(rec)

    def store(
        self,
        key: str,
        parsed: BaseModel | None,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        error: str | None = None,
    ) -> Recorded:
        """녹화한다. 같은 키가 이미 있으면 처음 것을 유지하고 그것을 돌려준다(재현성)."""
        with self._lock:
            if key in self._entries:
                return self._entries[key]
            rec = Recorded(
                parsed.model_dump(mode="json") if parsed is not None else None,
                input_tokens,
                output_tokens,
                latency_ms,
                error,
            )
            self._entries[key] = rec
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, **rec.__dict__}, ensure_ascii=False) + "\n")
            self.recorded += 1
            return rec

    def summary(self) -> dict:
        return {
            "mode": self.mode.value,
            "file": self.path.name,
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "recorded": self.recorded,
        }
