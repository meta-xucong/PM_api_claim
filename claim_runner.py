from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from web3 import Web3

from calldata_builder import (
    build_ctf_redeem_calldata,
    build_negative_risk_redeem_calldata,
)
from models import AccountConfig, AppConfig, RunMode
from positions_client import ClaimTask, ClaimTaskType, ClaimableResult, PositionsClient
from safe_signer import (
    SafeContractConfig,
    build_safe_transaction_request,
    derive_safe_wallet,
    transaction_request_to_dict,
)
from relayer_client import RelayerAuth, RelayerClient

logger = logging.getLogger(__name__)

ERC1155_BALANCE_OF_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    }
]


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
        self.web3 = Web3(Web3.HTTPProvider(config.rpc_url))
        self.ctf_contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(self.config.contracts.ctf_contract),
            abi=ERC1155_BALANCE_OF_ABI,
        )
        self._balance_cache: dict[tuple[str, int], int] = {}

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

        if not result.claim_tasks:
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
            claims=[
                {
                    "conditionId": task.condition_id,
                    "claim_type": task.task_type.value,
                }
                for task in result.claim_tasks
            ],
        )
        summary.total_conditions += len(result.claim_tasks)

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

        for task in result.claim_tasks:
            self._run_task(
                account=account,
                task=task,
                relayer=relayer,
                safe_config=safe_config,
                summary=summary,
            )

    def _get_ctf_token_balance(self, proxy_wallet: str, token_id: int | None) -> int:
        if token_id is None:
            return 0
        key = (proxy_wallet.lower(), int(token_id))
        if key in self._balance_cache:
            return self._balance_cache[key]

        try:
            balance = self.ctf_contract.functions.balanceOf(
                Web3.to_checksum_address(proxy_wallet),
                int(token_id),
            ).call()
            amount = int(balance)
        except Exception as exc:
            _structured_log(
                "negative_risk_balance_read_failed",
                proxy_wallet=proxy_wallet,
                token_id=token_id,
                error=str(exc),
            )
            amount = 0

        self._balance_cache[key] = amount
        return amount

    def _build_claim_call(self, account: AccountConfig, task: ClaimTask) -> tuple[str, str, dict[str, Any] | None]:
        if task.task_type == ClaimTaskType.CTF:
            calldata = build_ctf_redeem_calldata(
                collateral_token=self.config.contracts.collateral_token,
                condition_id=task.condition_id,
                index_sets=[1, 2],
            )
            return self.config.contracts.ctf_contract, calldata, None

        yes_amount = self._get_ctf_token_balance(account.proxy_wallet, task.yes_token_id)
        no_amount = self._get_ctf_token_balance(account.proxy_wallet, task.no_token_id)
        if yes_amount == 0 and no_amount == 0:
            return "", "", {
                "yes_amount": yes_amount,
                "no_amount": no_amount,
                "yes_token_id": task.yes_token_id,
                "no_token_id": task.no_token_id,
            }

        calldata = build_negative_risk_redeem_calldata(
            condition_id=task.condition_id,
            amounts=[yes_amount, no_amount],
        )
        return (
            self.config.contracts.negative_risk_adapter,
            calldata,
            {
                "yes_amount": yes_amount,
                "no_amount": no_amount,
                "yes_token_id": task.yes_token_id,
                "no_token_id": task.no_token_id,
            },
        )

    def _run_task(
        self,
        *,
        account: AccountConfig,
        task: ClaimTask,
        relayer: RelayerClient,
        safe_config: SafeContractConfig,
        summary: RunSummary,
    ) -> None:
        to_address, redeem_calldata, extra = self._build_claim_call(account, task)
        if not to_address:
            _structured_log(
                "skip_negative_risk_zero_balance",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                conditionId=task.condition_id,
                claim_type=task.task_type.value,
                details=extra or {},
            )
            return

        if self.mode == RunMode.DRY_RUN:
            _structured_log(
                "dry_run_claimable",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                conditionId=task.condition_id,
                claim_type=task.task_type.value,
                details=extra or {},
            )
            return

        safe_nonce = relayer.get_nonce(account.signer_address, tx_type="SAFE")
        request = build_safe_transaction_request(
            private_key=account.signer_private_key,
            from_address=account.signer_address,
            to_address=to_address,
            calldata=redeem_calldata,
            nonce=safe_nonce,
            chain_id=self.config.chain_id,
            safe_config=safe_config,
            metadata=f"auto-claim:{task.task_type.value}:{task.condition_id}",
        )
        request_payload = transaction_request_to_dict(request)

        if self.mode == RunMode.BUILD_ONLY:
            _structured_log(
                "build_only_payload",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                conditionId=task.condition_id,
                claim_type=task.task_type.value,
                details=extra or {},
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
            conditionId=task.condition_id,
            claim_type=task.task_type.value,
            details=extra or {},
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
            conditionId=task.condition_id,
            claim_type=task.task_type.value,
            details=extra or {},
            transactionID=transaction_id,
            transactionHash=final_hash,
            final_state=final_state,
        )

        if final_state == "STATE_CONFIRMED":
            summary.confirmed_transactions += 1
        else:
            summary.failed_transactions += 1
