from decimal import Decimal

from apps.telegram.templates import TEST_MESSAGE_PREFIX, AlertMessageContext, render_alert_message


def _context(**overrides):
    defaults = {
        "token_symbol": "TOKEN",
        "state": "confirmed",
        "market_cap": Decimal("240000"),
        "liquidity_usd": Decimal("78000"),
        "probability_2x": Decimal("0.87"),
        "probability_3x": Decimal("0.71"),
        "narrative_name": "Viral AI Meme",
        "narrative_strength": Decimal("91"),
        "narrative_momentum": Decimal("94"),
        "momentum_score": Decimal("89"),
        "holder_growth_pct": Decimal("42"),
        "smart_money_count": 6,
        "buy_pressure_pct": Decimal("72"),
        "risk_score": Decimal("17"),
        "reasons": ["5m volume accelerated 4.2x", "Holder growth accelerated"],
    }
    defaults.update(overrides)
    return AlertMessageContext(**defaults)


class TestRenderAlertMessage:
    def test_always_includes_a_why_now_explanation(self):
        message = render_alert_message(_context())
        assert "WHY NOW?" in message

    def test_includes_the_why_now_reasons(self):
        message = render_alert_message(_context())
        assert "5m volume accelerated 4.2x" in message
        assert "Holder growth accelerated" in message

    def test_includes_token_and_state(self):
        message = render_alert_message(_context(token_symbol="PEPE", state="breakout"))
        assert "$PEPE" in message
        assert "BREAKOUT" in message

    def test_missing_data_shows_unknown_not_zero(self):
        message = render_alert_message(_context(market_cap=None, liquidity_usd=None))
        assert "Market Cap: Unknown" in message
        assert "Liquidity: Unknown" in message
        assert "Market Cap: $0" not in message

    def test_no_narrative_omits_the_narrative_section(self):
        message = render_alert_message(_context(narrative_name=""))
        assert "Narrative:" not in message

    def test_with_narrative_shows_all_three_narrative_fields(self):
        message = render_alert_message(_context())
        assert "Narrative: Viral AI Meme" in message
        assert "Narrative Strength: 91.0/100" in message
        assert "Narrative Momentum: 94.0/100" in message

    def test_probability_shown_as_percent(self):
        message = render_alert_message(_context(probability_2x=Decimal("0.87")))
        assert "2X Probability: 87.0%" in message

    def test_no_reasons_still_produces_a_why_now_section(self):
        message = render_alert_message(_context(reasons=[]))
        assert "WHY NOW?" in message

    def test_priority_flag_is_visible(self):
        message = render_alert_message(_context(is_priority=True))
        assert "PRIORITY" in message

    def test_non_priority_has_no_priority_marker(self):
        message = render_alert_message(_context(is_priority=False))
        assert "PRIORITY" not in message

    def test_test_message_is_unmistakably_labeled(self):
        message = render_alert_message(_context(is_test=True))
        assert message.startswith(TEST_MESSAGE_PREFIX)

    def test_invalidated_state_explains_the_breakdown(self):
        message = render_alert_message(_context(state="invalidated"))
        assert "broken down" in message

    def test_holder_growth_is_signed(self):
        message = render_alert_message(_context(holder_growth_pct=Decimal("42")))
        assert "Holder Growth: +42.0%" in message

    def test_negative_holder_growth_is_not_double_signed(self):
        message = render_alert_message(_context(holder_growth_pct=Decimal("-10")))
        assert "Holder Growth: -10.0%" in message
