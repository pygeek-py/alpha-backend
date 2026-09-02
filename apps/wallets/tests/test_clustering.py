from datetime import datetime, timedelta

from apps.wallets.clustering import TxRecord, find_wallet_clusters

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


def _tx(wallet: str, seconds_offset: int, side: str = "buy") -> TxRecord:
    return TxRecord(
        wallet_address=wallet, occurred_at=BASE_TIME + timedelta(seconds=seconds_offset), side=side
    )


class TestFindWalletClusters:
    def test_no_transactions_no_clusters(self):
        assert find_wallet_clusters({}) == []

    def test_single_wallet_never_clusters_with_itself(self):
        transactions_by_token = {
            "TokenA": [_tx("W1", 0), _tx("W1", 1), _tx("W1", 2)],
        }
        assert find_wallet_clusters(transactions_by_token) == []

    def test_two_wallets_coordinated_on_enough_tokens_form_a_cluster(self):
        transactions_by_token = {
            "TokenA": [_tx("W1", 0), _tx("W2", 1)],
            "TokenB": [_tx("W1", 0), _tx("W2", 2)],
            "TokenC": [_tx("W1", 0), _tx("W2", 1)],
        }
        clusters = find_wallet_clusters(transactions_by_token)
        assert len(clusters) == 1
        assert clusters[0].wallet_addresses == frozenset({"W1", "W2"})
        assert clusters[0].shared_token_count == 3

    def test_below_minimum_shared_tokens_does_not_cluster(self):
        transactions_by_token = {
            "TokenA": [_tx("W1", 0), _tx("W2", 1)],
            "TokenB": [_tx("W1", 0), _tx("W2", 1)],
        }
        assert find_wallet_clusters(transactions_by_token) == []

    def test_wide_time_gap_does_not_count_as_coordinated(self):
        transactions_by_token = {
            "TokenA": [_tx("W1", 0), _tx("W2", 300)],
            "TokenB": [_tx("W1", 0), _tx("W2", 300)],
            "TokenC": [_tx("W1", 0), _tx("W2", 300)],
        }
        assert find_wallet_clusters(transactions_by_token) == []

    def test_different_sides_do_not_count_as_coordinated(self):
        # W1 buys, W2 sells at the same instant -- not coordinated entry.
        transactions_by_token = {
            "TokenA": [_tx("W1", 0, "buy"), _tx("W2", 0, "sell")],
            "TokenB": [_tx("W1", 0, "buy"), _tx("W2", 0, "sell")],
            "TokenC": [_tx("W1", 0, "buy"), _tx("W2", 0, "sell")],
        }
        assert find_wallet_clusters(transactions_by_token) == []

    def test_three_wallets_transitively_group_into_one_cluster(self):
        # W1+W2 coordinate on A/B/C; W2+W3 coordinate on D/E/F. All three
        # should end up in ONE cluster via the shared W2 link.
        transactions_by_token = {
            "TokenA": [_tx("W1", 0), _tx("W2", 1)],
            "TokenB": [_tx("W1", 0), _tx("W2", 1)],
            "TokenC": [_tx("W1", 0), _tx("W2", 1)],
            "TokenD": [_tx("W2", 0), _tx("W3", 1)],
            "TokenE": [_tx("W2", 0), _tx("W3", 1)],
            "TokenF": [_tx("W2", 0), _tx("W3", 1)],
        }
        clusters = find_wallet_clusters(transactions_by_token)
        assert len(clusters) == 1
        assert clusters[0].wallet_addresses == frozenset({"W1", "W2", "W3"})

    def test_unrelated_wallet_pairs_form_separate_clusters(self):
        transactions_by_token = {
            "TokenA": [_tx("W1", 0), _tx("W2", 1)],
            "TokenB": [_tx("W1", 0), _tx("W2", 1)],
            "TokenC": [_tx("W1", 0), _tx("W2", 1)],
            "TokenD": [_tx("W3", 0), _tx("W4", 1)],
            "TokenE": [_tx("W3", 0), _tx("W4", 1)],
            "TokenF": [_tx("W3", 0), _tx("W4", 1)],
        }
        clusters = find_wallet_clusters(transactions_by_token)
        assert len(clusters) == 2
        wallet_sets = {c.wallet_addresses for c in clusters}
        assert frozenset({"W1", "W2"}) in wallet_sets
        assert frozenset({"W3", "W4"}) in wallet_sets

    def test_three_wallets_coordinating_together_form_one_cluster(self):
        transactions_by_token = {
            "TokenA": [_tx("W1", 0), _tx("W2", 1), _tx("W3", 2)],
            "TokenB": [_tx("W1", 0), _tx("W2", 1), _tx("W3", 2)],
            "TokenC": [_tx("W1", 0), _tx("W2", 1), _tx("W3", 2)],
        }
        clusters = find_wallet_clusters(transactions_by_token)
        assert len(clusters) == 1
        assert clusters[0].wallet_addresses == frozenset({"W1", "W2", "W3"})
