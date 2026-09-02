from decimal import Decimal

from apps.tokens.live_feed import filter_rows, sort_rows


def _row(**overrides):
    defaults = {
        "token_id": 1,
        "opportunity_score": Decimal("50"),
        "risk_score": Decimal("20"),
        "holder_count": 100,
        "state": "watching",
    }
    defaults.update(overrides)
    return defaults


class TestSortRows:
    def test_default_field_falls_back_when_unrecognized(self):
        rows = [
            _row(token_id=1, opportunity_score=Decimal("10")),
            _row(token_id=2, opportunity_score=Decimal("90")),
        ]
        result = sort_rows(rows, "not_a_real_field")
        assert [r["token_id"] for r in result] == [2, 1]

    def test_ascending_order(self):
        rows = [_row(token_id=1, risk_score=Decimal("80")), _row(token_id=2, risk_score=Decimal("20"))]
        result = sort_rows(rows, "risk_score")
        assert [r["token_id"] for r in result] == [2, 1]

    def test_descending_order(self):
        rows = [_row(token_id=1, risk_score=Decimal("20")), _row(token_id=2, risk_score=Decimal("80"))]
        result = sort_rows(rows, "-risk_score")
        assert [r["token_id"] for r in result] == [2, 1]

    def test_missing_values_always_sort_last_ascending(self):
        rows = [
            _row(token_id=1, holder_count=None),
            _row(token_id=2, holder_count=50),
        ]
        result = sort_rows(rows, "holder_count")
        assert [r["token_id"] for r in result] == [2, 1]

    def test_missing_values_always_sort_last_descending(self):
        rows = [
            _row(token_id=1, holder_count=None),
            _row(token_id=2, holder_count=50),
        ]
        result = sort_rows(rows, "-holder_count")
        assert [r["token_id"] for r in result] == [2, 1]

    def test_empty_list(self):
        assert sort_rows([], "-opportunity_score") == []


class TestFilterRows:
    def test_no_filter_returns_all(self):
        rows = [_row(state="watching"), _row(state="confirmed")]
        assert filter_rows(rows) == rows

    def test_filters_by_state(self):
        rows = [_row(token_id=1, state="watching"), _row(token_id=2, state="confirmed")]
        result = filter_rows(rows, state="confirmed")
        assert [r["token_id"] for r in result] == [2]

    def test_no_matches_returns_empty(self):
        rows = [_row(state="watching")]
        assert filter_rows(rows, state="breakout") == []
