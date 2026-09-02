"""Token age feature (PRD S15). The rest of the intelligence pipeline uses
this bucket to decide which signals matter at a given lifecycle stage -- a
3-minute-old token isn't evaluated the same way as a 4-hour-old one. Pure,
no DB access.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone


@dataclass(frozen=True)
class TokenAge:
    age: timedelta
    bucket: str  # "0_5m" | "5_30m" | "30m_3h" | "3h_plus"


def get_token_age(token, *, as_of: datetime | None = None) -> TokenAge | None:
    if token.launched_at is None:
        return None

    now = as_of or timezone.now()
    age = now - token.launched_at

    if age < timedelta(minutes=5):
        bucket = "0_5m"
    elif age < timedelta(minutes=30):
        bucket = "5_30m"
    elif age < timedelta(hours=3):
        bucket = "30m_3h"
    else:
        bucket = "3h_plus"

    return TokenAge(age=age, bucket=bucket)
