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
