from datetime import timedelta

from django.utils import timezone

from apps.tokens.features import get_token_age
from apps.tokens.models import Token


def _token_launched(minutes_ago: float | None) -> Token:
    launched_at = None if minutes_ago is None else timezone.now() - timedelta(minutes=minutes_ago)
    return Token(address="AgeTestMint", launched_at=launched_at)


class TestGetTokenAge:
    def test_none_when_launch_time_unknown(self):
        assert get_token_age(_token_launched(None)) is None

    def test_0_5m_bucket(self):
        result = get_token_age(_token_launched(3))
        assert result.bucket == "0_5m"

    def test_5_30m_bucket(self):
        result = get_token_age(_token_launched(15))
        assert result.bucket == "5_30m"

    def test_30m_3h_bucket(self):
        result = get_token_age(_token_launched(90))
        assert result.bucket == "30m_3h"

    def test_3h_plus_bucket(self):
        result = get_token_age(_token_launched(300))
        assert result.bucket == "3h_plus"

    def test_boundary_at_exactly_5_minutes_is_5_30m_not_0_5m(self):
        result = get_token_age(_token_launched(5))
        assert result.bucket == "5_30m"

    def test_as_of_parameter_is_used_instead_of_now(self):
        token = Token(address="AgeTestMint2", launched_at=timezone.now())
        fixed_later = timezone.now() + timedelta(hours=4)
        result = get_token_age(token, as_of=fixed_later)
        assert result.bucket == "3h_plus"
