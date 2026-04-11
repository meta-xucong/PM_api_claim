from positions_client import extract_claimable_condition_ids
from models import Position


def test_positions_dedupe_and_negative_risk_skip() -> None:
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

    result = extract_claimable_condition_ids(positions)
    assert result.claimable_condition_ids == ["0x" + "11" * 32]
    assert result.skipped_negative_risk_condition_ids == ["0x" + "22" * 32]

