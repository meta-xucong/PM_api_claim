from web3 import Web3

from calldata_builder import (
    build_ctf_redeem_calldata,
    build_negative_risk_redeem_calldata,
)


CTF_REDEEM_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

NEGATIVE_RISK_REDEEM_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "conditionId", "type": "bytes32"},
            {"name": "amounts", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


def _encode_with_web3(
    collateral_token: str,
    condition_id: str,
) -> str:
    contract = Web3().eth.contract(address=Web3.to_checksum_address("0x" + "1" * 40), abi=CTF_REDEEM_ABI)
    args = [collateral_token, bytes(32), bytes.fromhex(condition_id[2:]), [1, 2]]

    if hasattr(contract, "encode_abi"):
        return contract.encode_abi("redeemPositions", args=args)
    if hasattr(contract, "encodeABI"):
        return contract.encodeABI(fn_name="redeemPositions", args=args)

    fn = contract.functions.redeemPositions(*args)
    if hasattr(fn, "_encode_transaction_data"):
        return fn._encode_transaction_data()
    raise AssertionError("web3 ABI encoding API not found")


def test_redeem_calldata_matches_web3() -> None:
    collateral_token = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    condition_id = "0xdd22472e552920b8438158ea7238bfadfa4f736aa4cee91a6b86c39ead110917"

    encoded = build_ctf_redeem_calldata(
        collateral_token=collateral_token,
        condition_id=condition_id,
        index_sets=[1, 2],
    )
    expected = _encode_with_web3(collateral_token, condition_id)
    assert encoded == expected


def _encode_negative_risk_with_web3(condition_id: str, amounts: list[int]) -> str:
    contract = Web3().eth.contract(
        address=Web3.to_checksum_address("0x" + "2" * 40),
        abi=NEGATIVE_RISK_REDEEM_ABI,
    )
    args = [bytes.fromhex(condition_id[2:]), amounts]

    if hasattr(contract, "encode_abi"):
        return contract.encode_abi("redeemPositions", args=args)
    if hasattr(contract, "encodeABI"):
        return contract.encodeABI(fn_name="redeemPositions", args=args)

    fn = contract.functions.redeemPositions(*args)
    if hasattr(fn, "_encode_transaction_data"):
        return fn._encode_transaction_data()
    raise AssertionError("web3 ABI encoding API not found")


def test_negative_risk_redeem_calldata_matches_web3() -> None:
    condition_id = "0xc21299c809f14a10d0d8dd3e0bb5bddc59db3943556b73cb84f3415509991740"
    amounts = [123, 456]

    encoded = build_negative_risk_redeem_calldata(
        condition_id=condition_id, amounts=amounts
    )
    expected = _encode_negative_risk_with_web3(condition_id, amounts)
    assert encoded == expected
