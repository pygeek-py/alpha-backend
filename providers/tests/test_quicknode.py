from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from providers.exceptions import ProviderError
from providers.quicknode import QuickNodeClient

BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

# Trimmed fixtures mirroring the real shape observed from a live QuickNode
# RPC endpoint during development (see providers/quicknode.py docstring).
MINT_ACCOUNT_INFO_REVOKED = {
    "result": {
        "value": {
            "data": {
                "parsed": {"info": {"mintAuthority": None, "freezeAuthority": None, "decimals": 5}},
            }
        }
    }
}
MINT_ACCOUNT_INFO_NOT_REVOKED = {
    "result": {
        "value": {
            "data": {
                "parsed": {
                    "info": {"mintAuthority": "SomeAuthorityAddr", "freezeAuthority": "SomeFreezeAddr"}
                },
            }
        }
    }
}
TOKEN_SUPPLY_RESPONSE = {
    "result": {"value": {"amount": "8799453795826365920", "decimals": 5, "uiAmount": 87994537958263.66}}
}
LARGEST_ACCOUNTS_RESPONSE = {
    "result": {"value": [{"address": "Holder1", "uiAmount": 7193508364031.432}]}
}


def _mock_response(payload: dict, status: int = 200) -> Mock:
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    response.text = str(payload)
    return response


class TestQuickNodeClient:
    def test_requires_rpc_url(self):
        with override_settings(QUICKNODE_RPC_URL=""):
            with pytest.raises(ProviderError, match="not configured"):
                QuickNodeClient()

    @patch("providers.quicknode.requests.post")
    def test_raises_on_rpc_error(self, mock_post):
        mock_post.return_value = _mock_response({"error": {"code": -32602, "message": "invalid params"}})
        client = QuickNodeClient(rpc_url="https://fake.example/token")
        with pytest.raises(ProviderError, match="invalid params"):
            client.call("getTokenSupply", ["bad-address"])

    @patch("providers.quicknode.requests.post")
    def test_get_token_supply(self, mock_post):
        mock_post.return_value = _mock_response(TOKEN_SUPPLY_RESPONSE)
        client = QuickNodeClient(rpc_url="https://fake.example/token")
        supply = client.get_token_supply(BONK)
        assert supply["uiAmount"] == 87994537958263.66

    @patch("providers.quicknode.requests.post")
    def test_get_token_largest_accounts(self, mock_post):
        mock_post.return_value = _mock_response(LARGEST_ACCOUNTS_RESPONSE)
        client = QuickNodeClient(rpc_url="https://fake.example/token")
        accounts = client.get_token_largest_accounts(BONK)
        assert accounts[0]["address"] == "Holder1"

    @patch("providers.quicknode.requests.post")
    def test_get_mint_authorities_both_revoked(self, mock_post):
        mock_post.return_value = _mock_response(MINT_ACCOUNT_INFO_REVOKED)
        client = QuickNodeClient(rpc_url="https://fake.example/token")
        mint_revoked, freeze_revoked = client.get_mint_authorities(BONK)
        assert mint_revoked is True
        assert freeze_revoked is True

    @patch("providers.quicknode.requests.post")
    def test_get_mint_authorities_not_revoked(self, mock_post):
        mock_post.return_value = _mock_response(MINT_ACCOUNT_INFO_NOT_REVOKED)
        client = QuickNodeClient(rpc_url="https://fake.example/token")
        mint_revoked, freeze_revoked = client.get_mint_authorities(BONK)
        assert mint_revoked is False
        assert freeze_revoked is False

    @patch("providers.quicknode.requests.post")
    def test_get_mint_authorities_missing_account_returns_none(self, mock_post):
        mock_post.return_value = _mock_response({"result": {"value": None}})
        client = QuickNodeClient(rpc_url="https://fake.example/token")
        mint_revoked, freeze_revoked = client.get_mint_authorities("NonexistentMint")
        assert mint_revoked is None
        assert freeze_revoked is None
