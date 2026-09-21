"""운영 환경 설정 검증 (NFR-007, NFR-008).

운영에서 조용히 잘못 뜨는 것보다 기동을 막는 편이 낫다. 배포 후에 발견하면
이미 사용자 데이터가 오간 뒤다.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

VALID_PRODUCTION = dict(
    app_env="production",
    auth_mode="supabase",
    storage="postgres",
    database_url="postgresql://user:pw@host:5432/db",
    supabase_url="https://xxxx.supabase.co",
    cors_origins=["https://reg-radar.vercel.app"],
    # 운영에서는 비용 상한을 명시해야 한다. 기본값으로 숨겨 두면 설정을
    # 빠뜨렸는지 일부러 껐는지 구분되지 않는다.
    daily_analysis_limit_per_user=5,
    daily_analysis_limit_total=50,
)


class TestProductionGuards:
    def test_정상_설정은_통과한다(self):
        settings = Settings(**VALID_PRODUCTION)
        assert settings.app_env == "production"

    @pytest.mark.parametrize(
        "override,expected",
        [
            ({"auth_mode": "dev"}, "AUTH_MODE=dev"),
            ({"storage": "memory"}, "STORAGE=memory"),
            ({"database_url": ""}, "DATABASE_URL"),
            ({"supabase_url": "", "supabase_jwt_secret": ""}, "SUPABASE_URL"),
            ({"cors_origins": ["http://localhost:3000"]}, "localhost"),
        ],
    )
    def test_위험한_조합은_거부한다(self, override, expected):
        with pytest.raises(ValidationError, match=expected):
            Settings(**{**VALID_PRODUCTION, **override})

    def test_로컬에서는_같은_설정도_허용한다(self):
        """개발 편의를 운영 안전성과 맞바꾸지 않는다."""
        settings = Settings(
            app_env="local", auth_mode="dev", storage="memory",
            database_url="", cors_origins=["http://localhost:3000"],
        )
        assert settings.auth_mode == "dev"


class TestCorsParsing:
    def test_콤마_구분_문자열을_목록으로(self):
        """배포 플랫폼의 환경변수 입력란에 JSON을 넣는 것은 실수하기 쉽다."""
        settings = Settings(
            **{**VALID_PRODUCTION, "cors_origins": "https://a.com,https://b.com"}
        )
        assert settings.cors_origins == ["https://a.com", "https://b.com"]

    def test_공백을_정리한다(self):
        settings = Settings(
            **{**VALID_PRODUCTION, "cors_origins": " https://a.com , https://b.com "}
        )
        assert settings.cors_origins == ["https://a.com", "https://b.com"]

    def test_목록은_그대로_둔다(self):
        settings = Settings(**VALID_PRODUCTION)
        assert settings.cors_origins == ["https://reg-radar.vercel.app"]


class TestCostGuards:
    """공개 배포에서 AI 호출 비용에 상한이 없으면 기동을 막는다."""

    def test_상한이_없으면_기동을_막는다(self):
        with pytest.raises(ValidationError, match="DAILY_ANALYSIS_LIMIT_TOTAL"):
            Settings(
                **{**VALID_PRODUCTION, "openai_api_key": "sk-x", "daily_analysis_limit_total": 0}
            )

    def test_사용자별_상한도_필요하다(self):
        with pytest.raises(ValidationError, match="DAILY_ANALYSIS_LIMIT_PER_USER"):
            Settings(
                **{
                    **VALID_PRODUCTION,
                    "openai_api_key": "sk-x",
                    "daily_analysis_limit_per_user": 0,
                }
            )

    def test_LLM이_꺼져_있으면_요구하지_않는다(self):
        """AI를 안 쓰면 비용도 없다. 쓰지 않는 설정을 강요하지 않는다."""
        settings = Settings(
            **{
                **VALID_PRODUCTION,
                "openai_api_key": "",
                "daily_analysis_limit_total": 0,
                "daily_analysis_limit_per_user": 0,
            }
        )
        assert settings.app_env == "production"

    def test_로컬은_기본으로_제한하지_않는다(self):
        """비용 상한은 공개 배포의 요구이지 개발 환경의 요구가 아니다.

        기본값 10으로 두었더니 로컬 E2E가 한도에 걸려 멈췄다.
        """
        settings = Settings(_env_file=None)
        assert settings.daily_analysis_limit_per_user == 0
        assert settings.daily_analysis_limit_total == 0
