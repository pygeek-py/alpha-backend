from rest_framework import serializers


class LiveFeedRowSerializer(serializers.Serializer):
    """PRD S40 Live Token Feed columns. Serializes the plain dicts
    apps/tokens/services.py's get_live_feed assembles -- not a
    ModelSerializer, since each row is joined from several apps'
    snapshots/scores, not one model."""

    token_id = serializers.IntegerField()
    address = serializers.CharField()
    symbol = serializers.CharField()
    age_seconds = serializers.IntegerField()
    market_cap = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)
    liquidity_usd = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)
    volume_5m_usd = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)
    holder_count = serializers.IntegerField(allow_null=True)
    momentum_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    narrative_name = serializers.CharField(allow_null=True)
    smart_money_count = serializers.IntegerField()
    risk_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    opportunity_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    state = serializers.CharField()


class TokenOverviewSerializer(serializers.Serializer):
    token_id = serializers.IntegerField()
    address = serializers.CharField()
    symbol = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    age_seconds = serializers.IntegerField()
    market_cap = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)
    liquidity_usd = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)
    volume_5m_usd = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)
    holder_count = serializers.IntegerField(allow_null=True)
    state = serializers.CharField()


class ScoreCategoriesSerializer(serializers.Serializer):
    safety_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    liquidity_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    momentum_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    holder_growth_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    wallet_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    buy_pressure_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    price_structure_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    narrative_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    creator_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)


class ScoreBreakdownSerializer(serializers.Serializer):
    opportunity_score = serializers.DecimalField(max_digits=6, decimal_places=2)
    risk_score = serializers.DecimalField(max_digits=6, decimal_places=2)
    score_2x = serializers.DecimalField(max_digits=6, decimal_places=2)
    score_3x = serializers.DecimalField(max_digits=6, decimal_places=2)
    categories = ScoreCategoriesSerializer()
    explanation = serializers.JSONField()
    computed_at = serializers.DateTimeField()
    age_seconds = serializers.IntegerField()


class NarrativeBreakdownSerializer(serializers.Serializer):
    name = serializers.CharField()
    category = serializers.CharField()
    relevance_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    strength_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    momentum_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)


class OutcomeBreakdownSerializer(serializers.Serializer):
    reached_1_5x = serializers.BooleanField()
    reached_2x = serializers.BooleanField()
    reached_3x = serializers.BooleanField()
    reached_5x = serializers.BooleanField()
    reached_10x = serializers.BooleanField()
    max_multiple = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    max_drawdown_pct = serializers.DecimalField(max_digits=10, decimal_places=4, allow_null=True)
    time_to_2x = serializers.DurationField(allow_null=True)
    time_to_3x = serializers.DurationField(allow_null=True)
    time_to_5x = serializers.DurationField(allow_null=True)
    tracking_complete = serializers.BooleanField()


class WalletActivityRowSerializer(serializers.Serializer):
    wallet_address = serializers.CharField()
    wallet_label = serializers.CharField(allow_blank=True)
    classification = serializers.CharField()
    reputation_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    side = serializers.CharField()
    amount_usd = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)
    occurred_at = serializers.DateTimeField()


class TokenDetailSerializer(serializers.Serializer):
    overview = TokenOverviewSerializer()
    score = ScoreBreakdownSerializer(allow_null=True)
    narratives = NarrativeBreakdownSerializer(many=True)
    outcome = OutcomeBreakdownSerializer(allow_null=True)
    wallet_activity = WalletActivityRowSerializer(many=True)


class PricePointSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    price = serializers.DecimalField(max_digits=36, decimal_places=18)
    volume_5m = serializers.DecimalField(max_digits=24, decimal_places=6, allow_null=True)


class HolderPointSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    holder_count = serializers.IntegerField()


class TokenHistorySerializer(serializers.Serializer):
    price = PricePointSerializer(many=True)
    holders = HolderPointSerializer(many=True)
