from __future__ import annotations

from dataclasses import dataclass

from eth_abi import encode
from eth_utils import keccak, to_bytes, to_checksum_address

PROXY_SIGNATURE = "proxy((uint8,address,uint256,bytes)[])"


@dataclass(frozen=True)
class ProxyCall:
    type_code: int
    to: str
    value: str
    data: str


def encode_proxy_transaction_data(calls: list[ProxyCall]) -> str:
    function_selector = keccak(text=PROXY_SIGNATURE)[:4]
    tuple_values: list[tuple[int, str, int, bytes]] = []

    for call in calls:
        data_bytes = (
            to_bytes(hexstr=call.data)
            if call.data.startswith("0x")
            else to_bytes(hexstr=f"0x{call.data}")
        )
        tuple_values.append(
            (
                int(call.type_code),
                to_checksum_address(call.to),
                int(call.value),
                data_bytes,
            )
        )

    encoded_args = encode(["(uint8,address,uint256,bytes)[]"], [tuple_values])
    return f"0x{(function_selector + encoded_args).hex()}"

