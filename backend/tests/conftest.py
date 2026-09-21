from pathlib import Path

import pytest

from app.core.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def law_settings() -> Settings:
    return Settings(
        law_api_oc="testoc",
        law_api_base_url="https://www.law.go.kr/DRF",
        law_api_max_retries=1,
        openai_api_key="",
    )
