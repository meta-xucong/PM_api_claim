from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from calldata_builder import build_ctf_redeem_calldata
from models import AccountConfig, AppConfig, RunMode
from positions_client import ClaimableResult, PositionsClient
from safe_signer import (
    SafeContractConfig,
    build_safe_transaction_request,
    derive_safe_wallet,
    transaction_request_to_dict,
)
from relayer_client import RelayerAuth, RelayerClient

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    total_accounts: int = 0
    processed_accounts: int = 0
    total_conditions: int = 0
    submitted_transactions: int = 0
    confirmed_transactions: int = 0
    failed_transactions: int = 0


def _structured_log(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=True))


class ClaimRunner:
    def __init__(self, config: AppConfig, mode: RunMode):
        self.config = config
        self.mode = mode
        self.positions_client = PositionsClient(config)

    def run(self) -> RunSummary:
        summary = RunSummary(total_accounts=len(self.config.enabled_accounts()))
        for account in self.config.enabled_accounts():
            summary.processed_accounts += 1
            self._run_account(account, summary)
        return summary

    def _run_account(self, account: AccountConfig, summary: RunSummary) -> None:
        expected_safe = derive_safe_wallet(
            account.signer_address, self.config.contracts.safe_factory
        )
        if expected_safe.lower() != account.proxy_wallet.lower():
            raise ValueError(
                f"account {account.account_name} proxy_wallet mismatch: "
                f"config={account.proxy_wallet}, derived_safe={expected_safe}"
            )

        result: ClaimableResult = self.positions_client.find_claimable_conditions(
            account.proxy_wallet
        )
        if result.skipped_negative_risk_condition_ids:
            _structured_log(
                "skip_negative_risk",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                condition_ids=result.skipped_negative_risk_condition_ids,
            )

        if not result.claimable_condition_ids:
            _structured_log(
                "no_claimable_positions",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
            )
            return

        _structured_log(
            "claimable_positions",
            account_name=account.account_name,
            signer_address=account.signer_address,
            proxy_wallet=account.proxy_wallet,
            condition_ids=result.claimable_condition_ids,
        )
        summary.total_conditions += len(result.claimable_condition_ids)

        relayer = RelayerClient(
            self.config,
            RelayerAuth(
                api_key=account.relayer_api_key,
                api_key_address=account.relayer_api_key_address,
            ),
        )
        safe_config = SafeContractConfig(
            safe_factory=self.config.contracts.safe_factory,
            safe_multisend=self.config.contracts.safe_multisend,
        )
        if not relayer.get_deployed(account.proxy_wallet):
            _structured_log(
                "safe_not_deployed_skip",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
            )
            return

        for condition_id in result.claimable_condition_ids:
            self._run_condition(
                account=account,
                condition_id=condition_id,
                relayer=relayer,
                safe_config=safe_config,
                summary=summary,
            )

    def _run_condition(
        self,
        *,
        account: AccountConfig,
        condition_id: str,
        relayer: RelayerClient,
        safe_config: SafeContractConfig,
        summary: RunSummary,
    ) -> None:
        redeem_calldata = build_ctf_redeem_calldata(
            collateral_token=self.config.contracts.collateral_token,
            condition_id=condition_id,
            index_sets=[1, 2],
        )

        if self.mode == RunMode.DRY_RUN:
            _structured_log(
                "dry_run_claimable",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                conditionId=condition_id,
            )
            return

        safe_nonce = relayer.get_nonce(account.signer_address, tx_type="SAFE")
        request = build_safe_transaction_request(
            private_key=account.signer_private_key,
            from_address=account.signer_address,
            to_address=self.config.contracts.ctf_contract,
            calldata=redeem_calldata,
            nonce=safe_nonce,
            chain_id=self.config.chain_id,
            safe_config=safe_config,
            metadata=f"auto-claim:{condition_id}",
        )
        request_payload = transaction_request_to_dict(request)

        if self.mode == RunMode.BUILD_ONLY:
            _structured_log(
                "build_only_payload",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                conditionId=condition_id,
                payload=request_payload,
            )
            return

        submit_result = relayer.submit(request_payload)
        summary.submitted_transactions += 1

        transaction_id = str(submit_result.get("transactionID", ""))
        tx_hash = str(submit_result.get("transactionHash", ""))
        _structured_log(
            "submitted",
            account_name=account.account_name,
            signer_address=account.signer_address,
            proxy_wallet=account.proxy_wallet,
            conditionId=condition_id,
            transactionID=transaction_id,
            transactionHash=tx_hash,
            final_state="",
        )

        final_tx = relayer.poll_until_terminal(transaction_id)
        final_state = str(final_tx.get("state", ""))
        final_hash = str(final_tx.get("transactionHash", tx_hash))

        _structured_log(
            "finalized",
            account_name=account.account_name,
            signer_address=account.signer_address,
            proxy_wallet=account.proxy_wallet,
            conditionId=condition_id,
            transactionID=transaction_id,
            transactionHash=final_hash,
            final_state=final_state,
        )

        if final_state == "STATE_CONFIRMED":
            summary.confirmed_transactions += 1
        else:
            summary.failed_transactions += 1
