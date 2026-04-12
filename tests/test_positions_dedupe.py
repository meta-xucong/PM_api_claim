from positions_client import ClaimTaskType, extract_claimable_tasks
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

    result = extract_claimable_tasks(positions, enable_negative_risk_claim=False)
    assert len(result.claim_tasks) == 1
    assert result.claim_tasks[0].condition_id == "0x" + "11" * 32
    assert result.claim_tasks[0].task_type == ClaimTaskType.CTF
    assert result.skipped_negative_risk_condition_ids == ["0x" + "22" * 32]


def test_negative_risk_task_extracts_yes_no_assets() -> None:
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

    result = extract_claimable_tasks(positions, enable_negative_risk_claim=True)
    assert result.skipped_negative_risk_condition_ids == []
    assert len(result.claim_tasks) == 1
    assert result.claim_tasks[0].condition_id == "0x" + "44" * 32
    assert result.claim_tasks[0].task_type == ClaimTaskType.NEGATIVE_RISK
    assert result.claim_tasks[0].yes_token_id == 1001
    assert result.claim_tasks[0].no_token_id == 1002
