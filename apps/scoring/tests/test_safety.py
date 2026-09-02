"""Pure-logic tests for the safety engine -- deliberately DB-free (plain
unsaved model instances), since analyze_token_safety() takes every input as
an explicit argument rather than querying anything itself."""

from decimal import Decimal

from apps.holders.models import HolderSnapshot
from apps.liquidity.models import LiquiditySnapshot
from apps.market_data.models import TokenSnapshot
from apps.scoring.safety import analyze_token_safety
from apps.tokens.models import Token


def _safe_token(**overrides) -> Token:
    defaults = dict(
        address="SafeMint111",
        mint_authority_revoked=True,
        freeze_authority_revoked=True,
        is_mutable_metadata=False,
        creator_address="Creator111",
    )
    defaults.update(overrides)
    return Token(**defaults)


def _holder_snapshot(**overrides) -> HolderSnapshot:
    defaults = dict(
        holder_count=500, top_holder_pct=Decimal("5"), top5_pct=Decimal("15"), top10_pct=Decimal("25")
    )
    defaults.update(overrides)
    return HolderSnapshot(**defaults)


def _liquidity_snapshot(**overrides) -> LiquiditySnapshot:
    defaults = dict(liquidity_usd=Decimal("50000"), lp_locked=True, lp_burned=False)
    defaults.update(overrides)
    return LiquiditySnapshot(**defaults)


def _token_snapshot(**overrides) -> TokenSnapshot:
    defaults = dict(price=Decimal("0.001"), buy_volume_5m=Decimal("1000"), sell_volume_5m=Decimal("500"))
    defaults.update(overrides)
    return TokenSnapshot(**defaults)


class TestPerfectToken:
    def test_scores_100_and_is_low_risk(self):
        result = analyze_token_safety(
            _safe_token(),
            holder_snapshot=_holder_snapshot(),
            liquidity_snapshot=_liquidity_snapshot(),
            market_cap=Decimal("500000"),  # 10% liquidity/mcap ratio, comfortably above the 3% threshold
            recent_snapshots=[_token_snapshot() for _ in range(5)],
            prior_creator_token_count=0,
        )
        assert result.score == 100
        assert result.risk_level == "LOW"
        assert result.hard_rejection is False
        assert result.warnings == []

    def test_as_dict_has_expected_shape(self):
        result = analyze_token_safety(_safe_token())
        d = result.as_dict()
        assert set(d.keys()) == {
            "score", "risk_level", "checks", "warnings", "hard_rejection", "hard_rejection_reasons",
        }


class TestMintAuthority:
    def test_active_mint_authority_hard_rejects(self):
        result = analyze_token_safety(_safe_token(mint_authority_revoked=False))
        assert result.hard_rejection is True
        assert "Mint authority not revoked" in result.hard_rejection_reasons
        assert result.risk_level == "EXTREME"

    def test_unknown_mint_authority_is_neutral(self):
        result = analyze_token_safety(_safe_token(mint_authority_revoked=None))
        check = next(c for c in result.checks if c["name"] == "mint_authority")
        assert check["passed"] is None
        assert result.hard_rejection is False


class TestFreezeAuthority:
    def test_active_freeze_authority_hard_rejects(self):
        result = analyze_token_safety(_safe_token(freeze_authority_revoked=False))
        assert result.hard_rejection is True
        assert "Freeze authority not revoked" in result.hard_rejection_reasons


class TestMetadataMutability:
    def test_mutable_metadata_is_a_minor_warning_not_rejection(self):
        result = analyze_token_safety(_safe_token(is_mutable_metadata=True))
        assert result.hard_rejection is False
        assert result.score == 95  # -5 points only


class TestHolderConcentration:
    def test_no_snapshot_is_unknown(self):
        result = analyze_token_safety(_safe_token(), holder_snapshot=None)
        check = next(c for c in result.checks if c["name"] == "holder_concentration")
        assert check["passed"] is None

    def test_top_holder_above_70_percent_hard_rejects(self):
        result = analyze_token_safety(
            _safe_token(), holder_snapshot=_holder_snapshot(top_holder_pct=Decimal("75"))
        )
        assert result.hard_rejection is True

    def test_top_holder_50_to_70_percent_is_critical_not_rejection(self):
        result = analyze_token_safety(
            _safe_token(), holder_snapshot=_holder_snapshot(top_holder_pct=Decimal("60"))
        )
        assert result.hard_rejection is False
        assert result.score == 75  # -25 points

    def test_top_holder_30_to_50_percent_is_a_warning(self):
        result = analyze_token_safety(
            _safe_token(), holder_snapshot=_holder_snapshot(top_holder_pct=Decimal("35"))
        )
        assert result.score == 90  # -10 points

    def test_top_holder_below_30_percent_passes(self):
        result = analyze_token_safety(
            _safe_token(), holder_snapshot=_holder_snapshot(top_holder_pct=Decimal("10"))
        )
        assert result.score == 100

    def test_top5_and_top10_concentration_add_separate_warnings(self):
        result = analyze_token_safety(
            _safe_token(),
            holder_snapshot=_holder_snapshot(
                top_holder_pct=Decimal("10"), top5_pct=Decimal("90"), top10_pct=Decimal("95")
            ),
        )
        assert result.score == 100 - 10 - 5  # top5 warning (-10) + top10 warning (-5)


class TestLiquidity:
    def test_no_snapshot_is_unknown(self):
        result = analyze_token_safety(_safe_token(), liquidity_snapshot=None)
        check = next(c for c in result.checks if c["name"] == "liquidity_amount")
        assert check["passed"] is None

    def test_below_hard_reject_threshold_rejects(self):
        result = analyze_token_safety(
            _safe_token(), liquidity_snapshot=_liquidity_snapshot(liquidity_usd=Decimal("100"))
        )
        assert result.hard_rejection is True
        assert any("Liquidity below" in r for r in result.hard_rejection_reasons)

    def test_below_warning_threshold_warns_not_rejects(self):
        result = analyze_token_safety(
            _safe_token(), liquidity_snapshot=_liquidity_snapshot(liquidity_usd=Decimal("2000"))
        )
        assert result.hard_rejection is False
        assert result.score == 85  # -15 points

    def test_unlocked_lp_is_a_warning(self):
        result = analyze_token_safety(
            _safe_token(),
            liquidity_snapshot=_liquidity_snapshot(liquidity_usd=Decimal("50000"), lp_locked=False),
        )
        assert result.score == 85  # -15 points

    def test_unknown_lp_lock_status_is_neutral(self):
        result = analyze_token_safety(
            _safe_token(), liquidity_snapshot=_liquidity_snapshot(lp_locked=None)
        )
        check = next(c for c in result.checks if c["name"] == "lp_lock_status")
        assert check["passed"] is None

    def test_low_liquidity_to_mcap_ratio_warns(self):
        result = analyze_token_safety(
            _safe_token(),
            liquidity_snapshot=_liquidity_snapshot(liquidity_usd=Decimal("10000")),
            market_cap=Decimal("10000000"),  # ratio = 0.1%, well under the 3% threshold
        )
        assert result.score == 90  # -10 points

    def test_no_market_cap_leaves_ratio_check_unknown(self):
        result = analyze_token_safety(
            _safe_token(), liquidity_snapshot=_liquidity_snapshot(), market_cap=None
        )
        check = next(c for c in result.checks if c["name"] == "liquidity_mcap_ratio")
        assert check["passed"] is None


class TestCreatorHistory:
    def test_no_creator_address_is_unknown(self):
        result = analyze_token_safety(_safe_token(creator_address=""), prior_creator_token_count=5)
        check = next(c for c in result.checks if c["name"] == "creator_history")
        assert check["passed"] is None

    def test_count_not_looked_up_is_unknown(self):
        result = analyze_token_safety(_safe_token(), prior_creator_token_count=None)
        check = next(c for c in result.checks if c["name"] == "creator_history")
        assert check["passed"] is None

    def test_zero_prior_tokens_passes(self):
        result = analyze_token_safety(_safe_token(), prior_creator_token_count=0)
        assert result.score == 100

    def test_serial_deployer_warning_band(self):
        result = analyze_token_safety(_safe_token(), prior_creator_token_count=3)
        assert result.score == 90  # -10 points

    def test_serial_deployer_severe_band(self):
        result = analyze_token_safety(_safe_token(), prior_creator_token_count=8)
        assert result.score == 80  # -20 points
        assert result.hard_rejection is False  # serial deployment alone doesn't hard-reject


class TestSellRestriction:
    def test_insufficient_snapshots_is_unknown(self):
        result = analyze_token_safety(_safe_token(), recent_snapshots=[_token_snapshot()])
        check = next(c for c in result.checks if c["name"] == "sell_restriction")
        assert check["passed"] is None

    def test_sustained_buys_with_zero_sells_hard_rejects(self):
        snapshots = [
            _token_snapshot(buy_volume_5m=Decimal("500"), sell_volume_5m=Decimal("0")) for _ in range(5)
        ]
        result = analyze_token_safety(_safe_token(), recent_snapshots=snapshots)
        assert result.hard_rejection is True
        assert any("honeypot" in r for r in result.hard_rejection_reasons)

    def test_low_total_buy_volume_does_not_trigger_honeypot_check(self):
        # Total buy volume across 5 snapshots is below the $1000 threshold,
        # so a brand-new low-activity token isn't flagged as a honeypot.
        snapshots = [
            _token_snapshot(buy_volume_5m=Decimal("50"), sell_volume_5m=Decimal("0")) for _ in range(5)
        ]
        result = analyze_token_safety(_safe_token(), recent_snapshots=snapshots)
        assert result.hard_rejection is False

    def test_sells_present_passes(self):
        snapshots = [_token_snapshot() for _ in range(5)]  # buy=1000, sell=500 each
        result = analyze_token_safety(_safe_token(), recent_snapshots=snapshots)
        check = next(c for c in result.checks if c["name"] == "sell_restriction")
        assert check["passed"] is True


class TestWalletClustering:
    def test_always_reported_as_unknown(self):
        result = analyze_token_safety(_safe_token())
        check = next(c for c in result.checks if c["name"] == "suspicious_wallet_clustering")
        assert check["passed"] is None
        assert "Batch 6" in check["detail"]


class TestScoreFloorAndRiskBands:
    def test_score_never_goes_below_zero(self):
        result = analyze_token_safety(
            _safe_token(mint_authority_revoked=False, freeze_authority_revoked=False),
            holder_snapshot=_holder_snapshot(top_holder_pct=Decimal("80")),
            liquidity_snapshot=_liquidity_snapshot(liquidity_usd=Decimal("10")),
            prior_creator_token_count=10,
        )
        assert result.score == 0
        assert result.hard_rejection is True

    def test_risk_band_boundaries(self):
        # 80+ LOW, 60-79 MODERATE, 40-59 HIGH, <40 EXTREME. Drive the score to
        # each band via top-holder concentration deductions alone.
        low = analyze_token_safety(
            _safe_token(), holder_snapshot=_holder_snapshot(top_holder_pct=Decimal("10"))
        )
        assert low.score == 100
        assert low.risk_level == "LOW"

        moderate = analyze_token_safety(
            _safe_token(), holder_snapshot=_holder_snapshot(top_holder_pct=Decimal("60"))
        )
        assert moderate.score == 75
        assert moderate.risk_level == "MODERATE"

    def test_hard_rejection_forces_extreme_risk_level_even_with_a_decent_score(self):
        # Only liquidity is catastrophic; everything else is clean, so the
        # raw score stays fairly high -- but hard_rejection must still force
        # EXTREME rather than showing a falsely reassuring risk level.
        result = analyze_token_safety(
            _safe_token(),
            holder_snapshot=_holder_snapshot(),
            liquidity_snapshot=_liquidity_snapshot(liquidity_usd=Decimal("10")),
            prior_creator_token_count=0,
        )
        assert result.hard_rejection is True
        assert result.risk_level == "EXTREME"
        assert result.score > 40  # score alone would have suggested a less severe band
