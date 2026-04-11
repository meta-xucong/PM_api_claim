from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from eth_account import Account
from eth_utils import is_address, to_checksum_address
from pydantic import BaseModel, Field, field_validator, model_validator


class RunMode(StrEnum):
    DRY_RUN = "dry-run"
    BUILD_ONLY = "build-only"
    LIVE = "live"


class RelayerTransactionState(StrEnum):
    STATE_NEW = "STATE_NEW"
    STATE_EXECUTED = "STATE_EXECUTED"
    STATE_MINED = "STATE_MINED"
    STATE_CONFIRMED = "STATE_CONFIRMED"
    STATE_FAILED = "STATE_FAILED"
    STATE_INVALID = "STATE_INVALID"


class AccountConfig(BaseModel):
    account_name: str
    enabled: bool = True
    signer_private_key: str
    signer_address: str
    proxy_wallet: str
    relayer_api_key: str
    relayer_api_key_address: str

    @field_validator("signer_private_key")
    @classmethod
    def validate_private_key(cls, value: str) -> str:
        key = value.strip()
        if not key:
            raise ValueError("signer_private_key cannot be empty")
        normalized = key if key.startswith("0x") else f"0x{key}"
        if len(normalized) != 66:
            raise ValueError("signer_private_key must be 32 bytes hex")
        return normalized

    @field_validator("signer_address", "proxy_wallet", "relayer_api_key_address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        if not is_address(value):
            raise ValueError(f"invalid address: {value}")
        return to_checksum_address(value)

    @model_validator(mode="after")
    def validate_signer_match(self) -> "AccountConfig":
        derived = Account.from_key(self.signer_private_key).address
        if to_checksum_address(derived) != self.signer_address:
            raise ValueError(
                "signer_private_key does not match signer_address "
                f"for account {self.account_name}"
            )
        return self


class ChainContracts(BaseModel):
    proxy_factory: str = Field(default="0xaB45c5A4B0c941a2F231C04C3f49182e1A254052")
    relay_hub: str = Field(default="0xD216153c06E857cD7f72665E0aF1d7D82172F494")
    safe_factory: str = Field(default="0xaacFeEa03eb1561C4e67d661e40682Bd20E3541b")
    safe_multisend: str = Field(default="0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761")
    ctf_contract: str = Field(default="0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")
    collateral_token: str = Field(default="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")

    @field_validator("*")
    @classmethod
    def validate_address(cls, value: str) -> str:
        if not is_address(value):
            raise ValueError(f"invalid address: {value}")
        return to_checksum_address(value)


class AppConfig(BaseModel):
    chain_id: int = 137
    relayer_url: str = "https://relayer-v2.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"
    request_timeout_seconds: float = 15.0
    request_retry_total: int = 4
    request_retry_backoff_seconds: float = 0.6
    gas_price: str = "0"
    poll_interval_seconds: float = 3.0
    poll_max_attempts: int = 120
    positions_page_limit: int = 500
    contracts: ChainContracts = Field(default_factory=ChainContracts)
    accounts: list[AccountConfig]

    @model_validator(mode="after")
    def validate_chain_and_accounts(self) -> "AppConfig":
        if self.chain_id != 137:
            raise ValueError("chain_id must be 137 (Polygon mainnet) for this app")

        account_names = [a.account_name for a in self.accounts]
        if len(account_names) != len(set(account_names)):
            raise ValueError("account_name must be unique across accounts")
        return self

    def enabled_accounts(self) -> list[AccountConfig]:
        return [account for account in self.accounts if account.enabled]


class Position(BaseModel):
    proxyWallet: str | None = None
    conditionId: str
    size: Decimal | float | int
    redeemable: bool
    negativeRisk: bool | None = None

    @field_validator("conditionId")
    @classmethod
    def validate_condition_id(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
            raise ValueError(f"invalid conditionId: {value}")
        return value.lower()

    @property
    def is_negative_risk(self) -> bool:
        return bool(self.negativeRisk)

    @property
    def numeric_size(self) -> Decimal:
        return Decimal(str(self.size))


class RelayPayload(BaseModel):
    address: str
    nonce: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        if not is_address(value):
            raise ValueError(f"invalid relay address: {value}")
        return to_checksum_address(value)


class SignatureParams(BaseModel):
    gasPrice: str
    gasLimit: str
    relayerFee: str
    relayHub: str
    relay: str


class ProxyTransactionRequest(BaseModel):
    type: str = "PROXY"
    from_: str = Field(alias="from")
    to: str
    proxyWallet: str
    data: str
    nonce: str
    signature: str
    signatureParams: SignatureParams
    metadata: str = ""

    model_config = {"populate_by_name": True}

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


class SafeSignatureParams(BaseModel):
    gasPrice: str
    operation: str
    safeTxnGas: str
    baseGas: str
    gasToken: str
    refundReceiver: str


class SafeTransactionRequest(BaseModel):
    type: str = "SAFE"
    from_: str = Field(alias="from")
    to: str
    proxyWallet: str
    data: str
    nonce: str
    signature: str
    signatureParams: SafeSignatureParams
    metadata: str = ""

    model_config = {"populate_by_name": True}

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)
