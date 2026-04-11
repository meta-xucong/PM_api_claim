from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_bytes, to_checksum_address
from hexbytes import HexBytes

from models import SafeSignatureParams, SafeTransactionRequest

SAFE_INIT_CODE_HASH = "0x2bce2127ff07fb632d16c8347c4ebf501f4841168bed00d9e6ef715ddb6fcecf"
SAFE_TX_TYPEHASH = keccak(
    text=(
        "SafeTx(address to,uint256 value,bytes data,uint8 operation,uint256 safeTxGas,"
        "uint256 baseGas,uint256 gasPrice,address gasToken,address refundReceiver,"
        "uint256 nonce)"
    )
)
EIP712_DOMAIN_TYPEHASH = keccak(
    text="EIP712Domain(uint256 chainId,address verifyingContract)"
)
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class SafeContractConfig:
    safe_factory: str
    safe_multisend: str


def _normalize_hex_bytes(value: str) -> bytes:
    if value.startswith("0x"):
        return to_bytes(hexstr=value)
    return to_bytes(hexstr=f"0x{value}")


def get_create2_address(bytecode_hash: str, from_address: str, salt: bytes) -> str:
    bytecode_hash_bytes = _normalize_hex_bytes(bytecode_hash)
    from_address_bytes = _normalize_hex_bytes(from_address)
    digest = keccak(b"\xff" + from_address_bytes + salt + bytecode_hash_bytes)
    return to_checksum_address(digest[-20:].hex())


def derive_safe_wallet(address: str, safe_factory: str) -> str:
    signer_address = to_checksum_address(address)
    factory_address = to_checksum_address(safe_factory)
    salt = keccak(encode(["address"], [signer_address]))
    return get_create2_address(SAFE_INIT_CODE_HASH, factory_address, salt)


def create_safe_struct_hash(
    *,
    chain_id: int,
    safe_address: str,
    to: str,
    value: str,
    data: str,
    operation: int,
    safe_tx_gas: str,
    base_gas: str,
    gas_price: str,
    gas_token: str,
    refund_receiver: str,
    nonce: str,
) -> str:
    safe = to_checksum_address(safe_address)
    to_addr = to_checksum_address(to)
    gas_token_addr = to_checksum_address(gas_token)
    refund_addr = to_checksum_address(refund_receiver)
    data_bytes = _normalize_hex_bytes(data)

    domain_separator = keccak(
        encode(
            ["bytes32", "uint256", "address"],
            [EIP712_DOMAIN_TYPEHASH, int(chain_id), safe],
        )
    )
    safe_tx_hash = keccak(
        encode(
            [
                "bytes32",
                "address",
                "uint256",
                "bytes32",
                "uint8",
                "uint256",
                "uint256",
                "uint256",
                "address",
                "address",
                "uint256",
            ],
            [
                SAFE_TX_TYPEHASH,
                to_addr,
                int(value),
                keccak(data_bytes),
                int(operation),
                int(safe_tx_gas),
                int(base_gas),
                int(gas_price),
                gas_token_addr,
                refund_addr,
                int(nonce),
            ],
        )
    )
    typed_data_hash = keccak(b"\x19\x01" + domain_separator + safe_tx_hash)
    return f"0x{typed_data_hash.hex()}"


def sign_safe_struct_hash(private_key: str, struct_hash: str) -> str:
    message = encode_defunct(HexBytes(struct_hash))
    signature = Account.sign_message(message, private_key=private_key).signature.hex()
    return f"0x{signature}"


def split_and_pack_safe_signature(signature: str) -> str:
    sig = HexBytes(signature)
    if len(sig) != 65:
        raise ValueError(f"invalid signature length: {len(sig)}")

    r = int.from_bytes(sig[0:32], "big")
    s = int.from_bytes(sig[32:64], "big")
    v_raw = sig[64]

    if v_raw in (0, 1):
        v = v_raw + 31
    elif v_raw in (27, 28):
        v = v_raw + 4
    else:
        raise ValueError("invalid signature v value")

    packed = r.to_bytes(32, "big") + s.to_bytes(32, "big") + v.to_bytes(1, "big")
    return f"0x{packed.hex()}"


def build_safe_transaction_request(
    *,
    private_key: str,
    from_address: str,
    to_address: str,
    calldata: str,
    nonce: str,
    chain_id: int,
    safe_config: SafeContractConfig,
    metadata: str = "",
) -> SafeTransactionRequest:
    signer = to_checksum_address(from_address)
    safe_address = derive_safe_wallet(signer, safe_config.safe_factory)
    to = to_checksum_address(to_address)
    operation = 0
    safe_tx_gas = "0"
    base_gas = "0"
    gas_price = "0"
    gas_token = ZERO_ADDRESS
    refund_receiver = ZERO_ADDRESS

    struct_hash = create_safe_struct_hash(
        chain_id=chain_id,
        safe_address=safe_address,
        to=to,
        value="0",
        data=calldata,
        operation=operation,
        safe_tx_gas=safe_tx_gas,
        base_gas=base_gas,
        gas_price=gas_price,
        gas_token=gas_token,
        refund_receiver=refund_receiver,
        nonce=nonce,
    )
    signature = sign_safe_struct_hash(private_key, struct_hash)
    packed_signature = split_and_pack_safe_signature(signature)

    return SafeTransactionRequest(
        type="SAFE",
        from_=signer,
        to=to,
        proxyWallet=safe_address,
        data=calldata,
        nonce=str(nonce),
        signature=packed_signature,
        signatureParams=SafeSignatureParams(
            gasPrice=gas_price,
            operation=str(operation),
            safeTxnGas=safe_tx_gas,
            baseGas=base_gas,
            gasToken=gas_token,
            refundReceiver=refund_receiver,
        ),
        metadata=metadata,
    )


def transaction_request_to_dict(request: SafeTransactionRequest) -> dict[str, Any]:
    return request.to_payload()

