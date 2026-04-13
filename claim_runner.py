from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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


@dataclass(frozen=True)
class RotationPick:
    round_number: int
    account_name: str
    remaining_before: list[str]


def _structured_log(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=True))


def _calldata_selector_hex(calldata: str) -> str:
    if not isinstance(calldata, str):
        return ""
    text = calldata.strip().lower()
    if not text.startswith("0x") or len(text) < 10:
        return ""
    return text[:10]


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
        self._rng: random.Random = random.SystemRandom()
        self._live_lock_path: Path | None = None

    def run(self) -> RunSummary:
        enabled_accounts = self.config.enabled_accounts()
        summary = RunSummary(total_accounts=len(enabled_accounts))
        if not enabled_accounts:
            _structured_log("no_enabled_accounts")
            return summary

        # Anti-sybil execution strategy is enabled for live mode only.
        if self.mode == RunMode.LIVE:
            if not self._acquire_live_lock():
                _structured_log("live_run_locked_skip")
                return summary
            try:
                jitter_seconds, delay_seconds = self._apply_live_hourly_jitter()
                pick = self._pick_account_for_live_run(enabled_accounts)
                account_lookup = {account.account_name: account for account in enabled_accounts}
                account = account_lookup[pick.account_name]
                summary.processed_accounts = 1
                _structured_log(
                    "account_rotation_pick",
                    round_number=pick.round_number,
                    selected_account=pick.account_name,
                    remaining_before=pick.remaining_before,
                    jitter_seconds=jitter_seconds,
                    delay_seconds=delay_seconds,
                )
                try:
                    self._run_account(account, summary)
                finally:
                    self._mark_account_processed(
                        enabled_accounts=enabled_accounts,
                        pick=pick,
                    )
            finally:
                self._release_live_lock()
            return summary

        for account in enabled_accounts:
            summary.processed_accounts += 1
            self._run_account(account, summary)
        return summary

    def _state_file(self) -> Path:
        path = Path(self.config.rotation_state_path)
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()

    def _lock_file(self) -> Path:
        state = self._state_file()
        return state.with_suffix(state.suffix + ".lock")

    def _acquire_live_lock(self) -> bool:
        lock_path = self._lock_file()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "acquired_ts": now,
            },
            ensure_ascii=True,
        )

        for _ in range(2):
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                self._live_lock_path = lock_path
                return True
            except FileExistsError:
                try:
                    raw = json.loads(lock_path.read_text(encoding="utf-8"))
                    acquired_ts = int(raw.get("acquired_ts", 0))
                except Exception:
                    acquired_ts = 0
                # Break stale lock after 3 hours.
                if acquired_ts > 0 and now - acquired_ts <= 3 * 3600:
                    return False
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    return False
        return False

    def _release_live_lock(self) -> None:
        if self._live_lock_path is None:
            return
        try:
            self._live_lock_path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self._live_lock_path = None

    @staticmethod
    def _dedupe_keep_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    def _load_rotation_state(self, enabled_names: list[str]) -> dict[str, Any]:
        path = self._state_file()
        enabled_order = list(enabled_names)
        default_state = {
            "version": 1,
            "round_number": 1,
            "enabled_accounts": enabled_order,
            "remaining_accounts": enabled_order,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not path.exists():
            return default_state

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default_state

        if not isinstance(raw, dict):
            return default_state

        raw_enabled = raw.get("enabled_accounts")
        raw_remaining = raw.get("remaining_accounts")
        if not isinstance(raw_enabled, list) or not isinstance(raw_remaining, list):
            return default_state

        parsed_enabled = [str(item) for item in raw_enabled]
        if set(parsed_enabled) != set(enabled_order):
            return default_state

        remaining = [name for name in (str(item) for item in raw_remaining) if name in enabled_order]
        remaining = self._dedupe_keep_order(remaining)
        if not remaining:
            round_number = int(raw.get("round_number", 1)) + 1
            return {
                **default_state,
                "round_number": round_number,
            }

        round_number = max(1, int(raw.get("round_number", 1)))
        return {
            "version": 1,
            "round_number": round_number,
            "enabled_accounts": enabled_order,
            "remaining_accounts": remaining,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save_rotation_state(self, state: dict[str, Any]) -> None:
        path = self._state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)

    def _pick_account_for_live_run(self, enabled_accounts: list[AccountConfig]) -> RotationPick:
        enabled_names = [account.account_name for account in enabled_accounts]
        state = self._load_rotation_state(enabled_names)
        remaining = list(state["remaining_accounts"])
        if not remaining:
            # Defensive fallback; _load_rotation_state should normally avoid this.
            remaining = enabled_names[:]

        selected = self._rng.choice(remaining)
        return RotationPick(
            round_number=int(state["round_number"]),
            account_name=selected,
            remaining_before=remaining,
        )

    def _mark_account_processed(
        self,
        *,
        enabled_accounts: list[AccountConfig],
        pick: RotationPick,
    ) -> None:
        enabled_names = [account.account_name for account in enabled_accounts]
        state = self._load_rotation_state(enabled_names)
        remaining = [name for name in state["remaining_accounts"] if name != pick.account_name]

        round_number = int(state["round_number"])
        round_completed = len(remaining) == 0
        if round_completed:
            next_round = round_number + 1
            next_remaining = enabled_names[:]
        else:
            next_round = round_number
            next_remaining = remaining

        updated_state = {
            "version": 1,
            "round_number": next_round,
            "enabled_accounts": enabled_names,
            "remaining_accounts": next_remaining,
            "last_selected_account": pick.account_name,
            "last_completed_round": round_number if round_completed else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_rotation_state(updated_state)

        _structured_log(
            "account_rotation_progress",
            round_number=round_number,
            selected_account=pick.account_name,
            remaining_after=remaining,
            round_completed=round_completed,
            next_round_number=next_round,
        )

    def _apply_live_hourly_jitter(self) -> tuple[int, int]:
        if not self.config.enable_live_hourly_jitter:
            return 0, 0

        jitter_span = int(self.config.live_hourly_jitter_seconds)
        jitter_seconds = self._rng.randint(-jitter_span, jitter_span)
        now = int(time.time())
        hour_anchor = now - (now % 3600)
        if jitter_seconds >= 0:
            reference_hour_anchor = hour_anchor
            target_ts = reference_hour_anchor + jitter_seconds
        else:
            # Negative jitter means "execute before next top-of-hour".
            reference_hour_anchor = hour_anchor + 3600
            target_ts = reference_hour_anchor + jitter_seconds
        if target_ts <= now:
            target_ts = now
        delay_seconds = target_ts - now

        _structured_log(
            "live_hourly_jitter",
            reference_hour_anchor_utc=datetime.fromtimestamp(
                reference_hour_anchor, tz=timezone.utc
            ).isoformat(),
            target_utc=datetime.fromtimestamp(target_ts, tz=timezone.utc).isoformat(),
            now_utc=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            jitter_seconds=jitter_seconds,
            delay_seconds=delay_seconds,
        )
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return jitter_seconds, delay_seconds

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
        if result.unroutable_condition_ids:
            _structured_log(
                "skip_unroutable_conditions",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                condition_ids=result.unroutable_condition_ids,
                reasons=result.route_errors,
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
            if not task.ctf_index_sets:
                raise ValueError(
                    f"ctf task missing index sets for condition {task.condition_id}"
                )
            calldata = build_ctf_redeem_calldata(
                collateral_token=self.config.contracts.collateral_token,
                condition_id=task.condition_id,
                index_sets=list(task.ctf_index_sets),
            )
            return self.config.contracts.ctf_contract, calldata, {
                "ctf_index_sets": list(task.ctf_index_sets),
                "route_source_slug": task.route_source_slug,
            }

        yes_amount = self._get_ctf_token_balance(account.proxy_wallet, task.yes_token_id)
        no_amount = self._get_ctf_token_balance(account.proxy_wallet, task.no_token_id)
        if yes_amount == 0 and no_amount == 0:
            return "", "", {
                "yes_amount": yes_amount,
                "no_amount": no_amount,
                "yes_token_id": task.yes_token_id,
                "no_token_id": task.no_token_id,
                "route_source_slug": task.route_source_slug,
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
                "route_source_slug": task.route_source_slug,
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
        if to_address:
            _structured_log(
                "claim_route_decision",
                account_name=account.account_name,
                signer_address=account.signer_address,
                proxy_wallet=account.proxy_wallet,
                conditionId=task.condition_id,
                claim_type=task.task_type.value,
                to=to_address,
                calldata_selector=_calldata_selector_hex(redeem_calldata),
                details=extra or {},
            )

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
