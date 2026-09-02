"""Wallet clustering foundations (PRD S18). A first, explainable heuristic:
wallets whose transactions on the same token repeatedly land within a very
tight time window of each other, across *multiple* unrelated tokens, are
grouped as a probable cluster (same operator running several wallets,
commonly to bypass per-wallet limits or fake distributed demand).

This is deliberately simple -- pairwise co-occurrence counting plus
union-find grouping, not a general graph-clustering algorithm or on-chain
funding-source analysis. It's a foundation to build on, not a finished
system.

Pure function: `transactions_by_token` is pre-fetched, grouped by the caller
(services.py); nothing here touches the database.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

TIGHT_TIMING_WINDOW = timedelta(seconds=5)
MIN_SHARED_TOKENS_FOR_CLUSTER = 3


@dataclass(frozen=True)
class TxRecord:
    wallet_address: str
    occurred_at: object  # datetime -- kept loosely typed so tests can use plain objects
    side: str


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_a] = root_b


def _co_occurring_pairs_for_token(transactions: list[TxRecord]) -> set[tuple[str, str]]:
    """Wallet pairs whose transactions on this one token fall within the
    tight timing window of each other, same side (both buys or both
    sells -- coordinated entries/exits, not just "someone else traded
    nearby")."""
    by_side: dict[str, list[TxRecord]] = defaultdict(list)
    for tx in transactions:
        by_side[tx.side].append(tx)

    pairs: set[tuple[str, str]] = set()
    for side_txs in by_side.values():
        ordered = sorted(side_txs, key=lambda t: t.occurred_at)
        for i, tx_a in enumerate(ordered):
            for tx_b in ordered[i + 1 :]:
                if tx_b.occurred_at - tx_a.occurred_at > TIGHT_TIMING_WINDOW:
                    break
                if tx_a.wallet_address != tx_b.wallet_address:
                    pairs.add(tuple(sorted((tx_a.wallet_address, tx_b.wallet_address))))
    return pairs


@dataclass
class WalletCluster:
    wallet_addresses: frozenset[str]
    shared_token_count: int


def find_wallet_clusters(
    transactions_by_token: dict[str, list[TxRecord]],
) -> list[WalletCluster]:
    """`transactions_by_token` maps token address -> list of TxRecord for
    that token. Returns groups of 2+ wallets that co-occurred (per
    `_co_occurring_pairs_for_token`) on at least MIN_SHARED_TOKENS_FOR_CLUSTER
    distinct tokens.
    """
    pair_shared_token_counts: dict[tuple[str, str], int] = defaultdict(int)
    for transactions in transactions_by_token.values():
        for pair in _co_occurring_pairs_for_token(transactions):
            pair_shared_token_counts[pair] += 1

    qualifying_pairs = [
        pair for pair, count in pair_shared_token_counts.items() if count >= MIN_SHARED_TOKENS_FOR_CLUSTER
    ]
    if not qualifying_pairs:
        return []

    uf = _UnionFind()
    for a, b in qualifying_pairs:
        uf.union(a, b)

    groups: dict[str, set[str]] = defaultdict(set)
    for a, b in qualifying_pairs:
        root = uf.find(a)
        groups[root].add(a)
        groups[root].add(b)

    clusters = []
    for members in groups.values():
        # shared_token_count for the cluster as a whole: the strongest
        # (max) pairwise count among its members, as a simple, explainable
        # summary rather than an elaborate group-cohesion metric.
        max_shared = max(
            count
            for pair, count in pair_shared_token_counts.items()
            if pair[0] in members and pair[1] in members
        )
        clusters.append(WalletCluster(wallet_addresses=frozenset(members), shared_token_count=max_shared))

    return clusters
