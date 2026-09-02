"""Raw Solana JSON-RPC client via QuickNode. Uses only standard RPC methods
(getTokenSupply, getTokenLargestAccounts, getAccountInfo) -- no QuickNode-
specific add-ons required, so this works against any Solana RPC endpoint;
QuickNode is just the vendor currently configured via QUICKNODE_RPC_URL.

Response shapes verified live against BONK during development (getAccountInfo
with jsonParsed encoding returns null mintAuthority/freezeAuthority when
revoked -- confirmed against BONK, which has renounced both).
"""

import logging

import requests
from django.conf import settings

from providers.exceptions import ProviderError

logger = logging.getLogger("alpha.providers.quicknode")

TIMEOUT_SECONDS = 10


class QuickNodeClient:
    def __init__(self, rpc_url: str | None = None):
        self.rpc_url = rpc_url or settings.QUICKNODE_RPC_URL
        if not self.rpc_url:
            raise ProviderError("QUICKNODE_RPC_URL is not configured")

    def call(self, method: str, params: list) -> dict:
        try:
            response = requests.post(
                self.rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                headers={"Content-Type": "application/json"},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"QuickNode RPC call {method} failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(
                f"QuickNode RPC {method} returned {response.status_code}: {response.text[:200]}"
            )

        payload = response.json()
        if "error" in payload:
            raise ProviderError(f"QuickNode RPC {method} error: {payload['error']}")
        return payload["result"]

    def get_token_supply(self, mint_address: str) -> dict:
        """{"amount": str, "decimals": int, "uiAmount": float, "uiAmountString": str}"""
        return self.call("getTokenSupply", [mint_address])["value"]

    def get_token_largest_accounts(self, mint_address: str) -> list[dict]:
        """Up to 20 accounts, sorted descending by balance -- each has
        "address", "amount", "decimals", "uiAmount", "uiAmountString"."""
        return self.call("getTokenLargestAccounts", [mint_address])["value"]

    def get_mint_authorities(self, mint_address: str) -> tuple[bool | None, bool | None]:
        """Returns (mint_authority_revoked, freeze_authority_revoked). This is
        the authoritative on-chain source for these facts -- reads the SPL
        Token Mint account directly rather than relying on a third party's
        derived security score."""
        result = self.call("getAccountInfo", [mint_address, {"encoding": "jsonParsed"}])
        value = result.get("value")
        if not value:
            return None, None
        try:
            info = value["data"]["parsed"]["info"]
        except (KeyError, TypeError):
            return None, None
        return info.get("mintAuthority") is None, info.get("freezeAuthority") is None
