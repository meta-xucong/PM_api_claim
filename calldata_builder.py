from __future__ import annotations

from eth_abi import encode
from eth_utils import keccak, to_bytes, to_checksum_address

CTF_REDEEM_SIGNATURE = "redeemPositions(address,bytes32,bytes32,uint256[])"
NEGATIVE_RISK_REDEEM_SIGNATURE = "redeemPositions(bytes32,uint256[])"
PARENT_COLLECTION_ID_ZERO = b"\x00" * 32
DEFAULT_INDEX_SETS = [1, 2]


def _selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def _as_bytes32_hex(value: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError(f"conditionId must be hex with 0x prefix, got: {value}")
    raw = to_bytes(hexstr=value)
    if len(raw) != 32:
        raise ValueError(f"conditionId must be 32 bytes, got {len(raw)}")
    return raw


def build_ctf_redeem_calldata(
    collateral_token: str,
    condition_id: str,
    index_sets: list[int] | None = None,
) -> str:
    index_values = index_sets if index_sets is not None else DEFAULT_INDEX_SETS
    encoded_args = encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [
            to_checksum_address(collateral_token),
            PARENT_COLLECTION_ID_ZERO,
            _as_bytes32_hex(condition_id),
            index_values,
        ],
    )
    return f"0x{(_selector(CTF_REDEEM_SIGNATURE) + encoded_args).hex()}"


def build_negative_risk_redeem_calldata(
    condition_id: str, amounts: list[int]
) -> str:
    if len(amounts) != 2:
        raise ValueError("negative risk redeem expects exactly 2 amounts [yes, no]")
    encoded_args = encode(
        ["bytes32", "uint256[]"],
        [
            _as_bytes32_hex(condition_id),
            [int(amounts[0]), int(amounts[1])],
        ],
    )
    return f"0x{(_selector(NEGATIVE_RISK_REDEEM_SIGNATURE) + encoded_args).hex()}"
