from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_abi.packed import encode_packed
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_bytes, to_checksum_address
from hexbytes import HexBytes
from web3 import Web3

from models import ProxyTransactionRequest, SignatureParams

PROXY_INIT_CODE_HASH = "0xd21df8dc65880a8606f09fe0ce3df9b8869287ab0b058be05aa9e8af6330a00b"
DEFAULT_GAS_LIMIT = 10_000_000


@dataclass(frozen=True)
class ProxyContractConfig:
    proxy_factory: str
    relay_hub: str


def _normalize_hex_bytes(value: str) -> bytes:
    if value.startswith("0x"):
        return to_bytes(hexstr=value)
    return to_bytes(hexstr=f"0x{value}")


def get_create2_address(bytecode_hash: str, from_address: str, salt: bytes) -> str:
    bytecode_hash_bytes = _normalize_hex_bytes(bytecode_hash)
    from_address_bytes = _normalize_hex_bytes(from_address)
    digest = keccak(b"\xff" + from_address_bytes + salt + bytecode_hash_bytes)
    return to_checksum_address(digest[-20:].hex())


def derive_proxy_wallet(address: str, proxy_factory: str) -> str:
    signer_address = to_checksum_address(address)
    factory_address = to_checksum_address(proxy_factory)
    salt = keccak(encode_packed(["address"], [signer_address]))
    return get_create2_address(PROXY_INIT_CODE_HASH, factory_address, salt)


def create_proxy_struct_hash(
    from_address: str,
    to: str,
    data: str,
    tx_fee: str,
    gas_price: str,
    gas_limit: str,
    nonce: str,
    relay_hub_address: str,
    relay_address: str,
) -> str:
    payload = (
        b"rlx:"
        + HexBytes(to_checksum_address(from_address))
        + HexBytes(to_checksum_address(to))
        + _normalize_hex_bytes(data)
        + int(tx_fee).to_bytes(32, "big")
        + int(gas_price).to_bytes(32, "big")
        + int(gas_limit).to_bytes(32, "big")
        + int(nonce).to_bytes(32, "big")
        + HexBytes(to_checksum_address(relay_hub_address))
        + HexBytes(to_checksum_address(relay_address))
    )
    return f"0x{keccak(payload).hex()}"


def sign_proxy_struct_hash(private_key: str, struct_hash: str) -> str:
    message = encode_defunct(HexBytes(struct_hash))
    signature = Account.sign_message(message, private_key=private_key).signature.hex()
    return f"0x{signature}"


def estimate_gas_limit(
    rpc_url: str | None,
    from_address: str,
    to_address: str,
    data: str,
) -> str:
    if not rpc_url:
        return str(DEFAULT_GAS_LIMIT)

    web3 = Web3(Web3.HTTPProvider(rpc_url))
    if not web3.is_connected():
        return str(DEFAULT_GAS_LIMIT)

    try:
        estimate = web3.eth.estimate_gas(
            {
                "from": to_checksum_address(from_address),
                "to": to_checksum_address(to_address),
                "data": data,
            }
        )
    except Exception:
        return str(DEFAULT_GAS_LIMIT)

    return str(estimate)


def build_proxy_transaction_request(
    *,
    private_key: str,
    from_address: str,
    proxy_tx_data: str,
    nonce: str,
    relay_address: str,
    proxy_config: ProxyContractConfig,
    gas_price: str = "0",
    gas_limit: str | None = None,
    metadata: str = "",
    rpc_url: str | None = None,
) -> ProxyTransactionRequest:
    signer = to_checksum_address(from_address)
    to = to_checksum_address(proxy_config.proxy_factory)
    resolved_gas_limit = (
        gas_limit
        if gas_limit and gas_limit != "0"
        else estimate_gas_limit(rpc_url, signer, to, proxy_tx_data)
    )
    struct_hash = create_proxy_struct_hash(
        from_address=signer,
        to=to,
        data=proxy_tx_data,
        tx_fee="0",
        gas_price=gas_price,
        gas_limit=resolved_gas_limit,
        nonce=nonce,
        relay_hub_address=proxy_config.relay_hub,
        relay_address=relay_address,
    )
    signature = sign_proxy_struct_hash(private_key, struct_hash)
    request = ProxyTransactionRequest(
        type="PROXY",
        from_=signer,
        to=to,
        proxyWallet=derive_proxy_wallet(signer, to),
        data=proxy_tx_data,
        nonce=str(nonce),
        signature=signature,
        signatureParams=SignatureParams(
            gasPrice=str(gas_price),
            gasLimit=str(resolved_gas_limit),
            relayerFee="0",
            relayHub=to_checksum_address(proxy_config.relay_hub),
            relay=to_checksum_address(relay_address),
        ),
        metadata=metadata,
    )
    return request


def transaction_request_to_dict(request: ProxyTransactionRequest) -> dict[str, Any]:
    return request.to_payload()

