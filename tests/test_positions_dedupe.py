from positions_client import (
    ClaimTaskType,
    ResolvedConditionRoute,
    extract_claimable_tasks,
)
from models import Position


def test_positions_dedupe_and_negative_risk_skip_when_disabled() -> None:
    positions = [
        Position.model_validate(
            {
                "conditionId": "0x" + "11" * 32,
                "size": 10,
                "redeemable": True,
                "negativeRisk": False,
            }
        ),
        Position.model_validate(
            {
                "conditionId": "0x" + "11" * 32,
                "size": 2,
                "redeemable": True,
                "negativeRisk": False,
            }
        ),
        Position.model_validate(
            {
                "conditionId": "0x" + "22" * 32,
                "size": 5,
                "redeemable": True,
                "negativeRisk": True,
            }
        ),
        Position.model_validate(
            {
                "conditionId": "0x" + "33" * 32,
                "size": 0,
                "redeemable": True,
                "negativeRisk": False,
            }
        ),
    ]

    def route_resolver(condition_id: str, _group: list[Position]) -> ResolvedConditionRoute:
        if condition_id == "0x" + "11" * 32:
            return ResolvedConditionRoute(
                task_type=ClaimTaskType.CTF,
                ctf_index_sets=(1, 2),
                source_slug="market-11",
            )
        if condition_id == "0x" + "22" * 32:
            return ResolvedConditionRoute(
                task_type=ClaimTaskType.NEGATIVE_RISK,
                yes_token_id=2001,
                no_token_id=2002,
                source_slug="market-22",
            )
        raise ValueError("unexpected condition")

    result = extract_claimable_tasks(
        positions,
        enable_negative_risk_claim=False,
        route_resolver=route_resolver,
    )
    assert len(result.claim_tasks) == 1
    assert result.claim_tasks[0].condition_id == "0x" + "11" * 32
    assert result.claim_tasks[0].task_type == ClaimTaskType.CTF
    assert result.claim_tasks[0].ctf_index_sets == (1, 2)
    assert result.skipped_negative_risk_condition_ids == ["0x" + "22" * 32]
    assert result.unroutable_condition_ids == []
    assert result.route_errors == {}


def test_negative_risk_task_uses_canonical_yes_no_token_ids() -> None:
    positions = [
        Position.model_validate(
            {
                "conditionId": "0x" + "44" * 32,
                "asset": "1001",
                "outcome": "Yes",
                "size": "2.5",
                "redeemable": True,
                "negativeRisk": True,
            }
        ),
        Position.model_validate(
            {
                "conditionId": "0x" + "44" * 32,
                "asset": "1002",
                "outcome": "No",
                "size": "1.5",
                "redeemable": True,
                "negativeRisk": True,
            }
        ),
    ]

    def route_resolver(condition_id: str, _group: list[Position]) -> ResolvedConditionRoute:
        assert condition_id == "0x" + "44" * 32
        return ResolvedConditionRoute(
            task_type=ClaimTaskType.NEGATIVE_RISK,
            yes_token_id=1001,
            no_token_id=1002,
            source_slug="market-44",
        )

    result = extract_claimable_tasks(
        positions,
        enable_negative_risk_claim=True,
        route_resolver=route_resolver,
    )
    assert result.skipped_negative_risk_condition_ids == []
    assert len(result.claim_tasks) == 1
    assert result.claim_tasks[0].condition_id == "0x" + "44" * 32
    assert result.claim_tasks[0].task_type == ClaimTaskType.NEGATIVE_RISK
    assert result.claim_tasks[0].yes_token_id == 1001
    assert result.claim_tasks[0].no_token_id == 1002
    assert result.unroutable_condition_ids == []


def test_unroutable_condition_is_blocked_instead_of_auto_fallback() -> None:
    positions = [
        Position.model_validate(
            {
                "conditionId": "0x" + "55" * 32,
                "size": 9,
                "redeemable": True,
            }
        )
    ]

    def route_resolver(_condition_id: str, _group: list[Position]) -> ResolvedConditionRoute:
        raise ValueError("missing canonical metadata")

    result = extract_claimable_tasks(
        positions,
        enable_negative_risk_claim=True,
        route_resolver=route_resolver,
    )
    assert result.claim_tasks == []
    assert result.skipped_negative_risk_condition_ids == []
    assert result.unroutable_condition_ids == ["0x" + "55" * 32]
    assert result.route_errors["0x" + "55" * 32] == "missing canonical metadata"
