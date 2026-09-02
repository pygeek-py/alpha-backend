from decimal import Decimal
from types import SimpleNamespace

from apps.narratives.detection import TokenIdentityText, compute_relevance, detect_narratives_for_token


def _narrative(narrative_id: int, keywords: list[str]):
    return SimpleNamespace(id=narrative_id, keywords=keywords)


class TestComputeRelevance:
    def test_no_keywords_means_zero_relevance(self):
        identity = TokenIdentityText(name="AI Dog", symbol="AID")
        score, in_name, in_desc = compute_relevance(identity, [])
        assert score == Decimal("0")
        assert in_name == []
        assert in_desc == []

    def test_keyword_matched_in_name(self):
        identity = TokenIdentityText(name="AI Robot Coin", symbol="AIR")
        score, in_name, in_desc = compute_relevance(identity, ["ai"])
        assert score == Decimal("35")
        assert in_name == ["ai"]
        assert in_desc == []

    def test_keyword_matched_only_in_description_scores_lower(self):
        identity = TokenIdentityText(
            name="Moon Coin", symbol="MOON", description="Powered by advanced ai models"
        )
        score, in_name, in_desc = compute_relevance(identity, ["ai"])
        assert score == Decimal("15")
        assert in_name == []
        assert in_desc == ["ai"]

    def test_matched_in_both_name_and_description_only_counts_once(self):
        identity = TokenIdentityText(name="AI Coin", symbol="AIC", description="An ai powered token")
        score, in_name, in_desc = compute_relevance(identity, ["ai"])
        # matched in name (35), not double-counted for the description hit too
        assert score == Decimal("35")
        assert in_name == ["ai"]
        assert in_desc == []

    def test_multiple_distinct_keywords_stack(self):
        identity = TokenIdentityText(name="AI Agent Bot", symbol="AAB")
        score, in_name, in_desc = compute_relevance(identity, ["ai", "agent", "bot"])
        assert score == Decimal("100")  # 3 * 35 = 105, capped at 100

    def test_prd_example_ai_dog_pepe_does_not_fully_qualify_as_ai(self):
        """PRD S21: "AI DOG PEPE 2026 does not automatically qualify as an
        AI narrative." A bare name mention of "AI" alongside unrelated
        words should score meaningfully below a token whose description
        actually reinforces the theme."""
        loose = TokenIdentityText(name="AI DOG PEPE 2026", symbol="ADP")
        loose_score, _, _ = compute_relevance(loose, ["ai", "agent", "gpt", "neural", "llm"])

        genuine = TokenIdentityText(
            name="AI Agent",
            symbol="AIA",
            description="A GPT-powered neural network agent trading autonomously",
        )
        genuine_score, _, _ = compute_relevance(genuine, ["ai", "agent", "gpt", "neural", "llm"])

        assert genuine_score > loose_score

    def test_case_insensitive_matching(self):
        identity = TokenIdentityText(name="ai COIN", symbol="AIC")
        score, in_name, _ = compute_relevance(identity, ["AI"])
        assert score == Decimal("35")

    def test_score_never_exceeds_100(self):
        identity = TokenIdentityText(
            name="ai agent bot neural gpt llm machine learning",
            symbol="X",
            description="ai agent bot neural gpt llm machine learning",
        )
        score, _, _ = compute_relevance(identity, ["ai", "agent", "bot", "neural", "gpt", "llm"])
        assert score == Decimal("100")


class TestDetectNarrativesForToken:
    def test_only_returns_matches_above_threshold(self):
        identity = TokenIdentityText(name="AI Coin", symbol="AIC")
        narratives = [_narrative(1, ["ai"]), _narrative(2, ["gaming", "metaverse"])]
        matches = detect_narratives_for_token(identity, narratives, min_relevance=Decimal("20"))
        assert len(matches) == 1
        assert matches[0].narrative_id == 1

    def test_weak_match_below_threshold_is_excluded(self):
        identity = TokenIdentityText(name="Some Coin", symbol="SC", description="mentions ai briefly")
        narratives = [_narrative(1, ["ai"])]
        # description-only match = 15, below the default 20 threshold
        matches = detect_narratives_for_token(identity, narratives)
        assert matches == []

    def test_token_can_match_multiple_narratives(self):
        identity = TokenIdentityText(name="AI Gaming Bot", symbol="AGB")
        narratives = [_narrative(1, ["ai", "bot"]), _narrative(2, ["gaming"])]
        matches = detect_narratives_for_token(identity, narratives)
        assert {m.narrative_id for m in matches} == {1, 2}

    def test_no_narratives_returns_empty(self):
        identity = TokenIdentityText(name="Anything", symbol="ANY")
        assert detect_narratives_for_token(identity, []) == []
