from __future__ import annotations

import pytest

from models import AppConfig, Position
from positions_client import ClaimTaskType, PositionsClient


def _build_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "accounts": [
                {
                    "account_name": "t1",
                    "enabled": False,
                    "signer_private_key": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
                    "signer_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                    "proxy_wallet": "0x8ba1f109551bD432803012645Ac136ddd64DBA72",
                    "relayer_api_key": "dummy",
                    "relayer_api_key_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                }
            ]
        }
    )


def test_resolve_route_negative_risk_uses_yes_no_from_market_metadata() -> None:
    condition_id = "0x" + "ab" * 32
    group = [
        Position.model_validate(
            {
                "conditionId": condition_id,
                "slug": "market-slug",
                "size": 1,
                "redeemable": True,
            }
        )
    ]
    client = PositionsClient(_build_config())
    client._fetch_market_by_slug = lambda _slug: {  # type: ignore[method-assign]
        "conditionId": condition_id,
        "negRisk": True,
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["111","222"]',
    }

    route = client._resolve_route(condition_id, group)
    assert route.task_type == ClaimTaskType.NEGATIVE_RISK
    assert route.yes_token_id == 111
    assert route.no_token_id == 222


def test_resolve_route_ctf_uses_outcome_count_for_index_sets() -> None:
    condition_id = "0x" + "cd" * 32
    group = [
        Position.model_validate(
            {
                "conditionId": condition_id,
                "slug": "market-slug",
                "size": 1,
                "redeemable": True,
            }
        )
    ]
    client = PositionsClient(_build_config())
    client._fetch_market_by_slug = lambda _slug: {  # type: ignore[method-assign]
        "conditionId": condition_id,
        "negRisk": False,
        "outcomes": '["A","B","C"]',
        "clobTokenIds": '["10","20","30"]',
    }

    route = client._resolve_route(condition_id, group)
    assert route.task_type == ClaimTaskType.CTF
    assert route.ctf_index_sets == (1, 2, 4)


def test_resolve_route_blocks_mismatched_condition_id() -> None:
    condition_id = "0x" + "ef" * 32
    group = [
        Position.model_validate(
            {
                "conditionId": condition_id,
                "slug": "market-slug",
                "size": 1,
                "redeemable": True,
            }
        )
    ]
    client = PositionsClient(_build_config())
    client._fetch_market_by_slug = lambda _slug: {  # type: ignore[method-assign]
        "conditionId": "0x" + "00" * 32,
        "negRisk": False,
        "outcomes": '["Yes","No"]',
        "clobTokenIds": '["1","2"]',
    }

    with pytest.raises(ValueError, match="condition mismatch"):
        client._resolve_route(condition_id, group)
