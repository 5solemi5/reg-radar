"""LLM provider 추상화 (NFR-012, ADR-002).

체인 코드는 이 모듈만 의존한다. provider/model 교체가 비즈니스 로직 수정으로
번지지 않도록, 구조화 출력 획득 경로를 한 곳으로 모은다.
"""

from __future__ import annotations

import logging
from typing import Protocol, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LlmUnavailableError(RuntimeError):
    """LLM 자격증명이 없거나 호출이 불가능한 상태 (ER-002)."""


class ChatModelFactory(Protocol):
    """테스트에서 FakeChatModel로 대체하기 위한 지점."""

    def __call__(self, settings: Settings) -> BaseChatModel: ...


def openai_chat_model(settings: Settings) -> BaseChatModel:
    if not settings.openai_api_key:
        raise LlmUnavailableError("OPENAI_API_KEY가 설정되지 않았습니다.")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        api_key=settings.openai_api_key,
    )


class LlmGateway:
    """구조화 출력 전용 게이트웨이.

    AP-06: 모든 체인은 Pydantic 스키마로만 결과를 받는다. 자유 텍스트 응답을
    파싱해 쓰는 경로를 두지 않는다.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        model_factory: ChatModelFactory = openai_chat_model,
    ):
        self.settings = settings or get_settings()
        self._model_factory = model_factory
        self._model: BaseChatModel | None = None

    @property
    def model(self) -> BaseChatModel:
        if self._model is None:
            self._model = self._model_factory(self.settings)
        return self._model

    @property
    def model_name(self) -> str:
        """관측성 기록용 모델 식별자 (NFR-009)."""
        return getattr(self.model, "model_name", None) or self.settings.llm_model

    def structured(self, schema: type[T]) -> Runnable:
        """스키마를 강제하는 Runnable을 반환한다.

        Structured Output 파싱 실패는 예외로 드러나야 하며(ER-003), 임의 보정하지 않는다.
        """
        return self.model.with_structured_output(schema)
