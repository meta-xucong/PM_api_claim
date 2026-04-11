from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models import AppConfig, RelayerTransactionState, RelayPayload


@dataclass(frozen=True)
class RelayerAuth:
    api_key: str
    api_key_address: str


class RelayerClient:
    def __init__(self, config: AppConfig, auth: RelayerAuth):
        self.config = config
        self.base_url = config.relayer_url.rstrip("/")
        self.auth = auth
        self.session = requests.Session()
        retry = Retry(
            total=config.request_retry_total,
            connect=config.request_retry_total,
            read=config.request_retry_total,
            status=config.request_retry_total,
            backoff_factor=config.request_retry_backoff_seconds,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "RELAYER_API_KEY": self.auth.api_key,
            "RELAYER_API_KEY_ADDRESS": self.auth.api_key_address,
        }

    def get_relay_payload(self, signer_address: str, tx_type: str = "PROXY") -> RelayPayload:
        response = self.session.get(
            f"{self.base_url}/relay-payload",
            params={"address": signer_address, "type": tx_type},
            headers=self._headers(),
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return RelayPayload.model_validate(payload)

    def get_nonce(self, signer_address: str, tx_type: str = "SAFE") -> str:
        response = self.session.get(
            f"{self.base_url}/nonce",
            params={"address": signer_address, "type": tx_type},
            headers=self._headers(),
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "nonce" not in payload:
            raise ValueError("/nonce response missing nonce")
        return str(payload["nonce"])

    def get_deployed(self, safe_address: str) -> bool:
        response = self.session.get(
            f"{self.base_url}/deployed",
            params={"address": safe_address},
            headers=self._headers(),
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return bool(payload.get("deployed"))
        return False

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/submit",
            json=payload,
            headers=self._headers(),
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("/submit response must be a JSON object")
        return data

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        response = self.session.get(
            f"{self.base_url}/transaction",
            params={"id": transaction_id},
            headers=self._headers(),
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data:
            tx = data[0]
            if isinstance(tx, dict):
                return tx
        return None

    def poll_until_terminal(self, transaction_id: str) -> dict[str, Any]:
        terminal_states = {
            RelayerTransactionState.STATE_CONFIRMED.value,
            RelayerTransactionState.STATE_FAILED.value,
            RelayerTransactionState.STATE_INVALID.value,
        }
        running_states = {
            RelayerTransactionState.STATE_NEW.value,
            RelayerTransactionState.STATE_EXECUTED.value,
            RelayerTransactionState.STATE_MINED.value,
        }

        for _ in range(self.config.poll_max_attempts):
            tx = self.get_transaction(transaction_id)
            if tx is not None:
                state = str(tx.get("state", "")).upper()
                if state in terminal_states:
                    return tx
                if state not in running_states:
                    return tx
            time.sleep(self.config.poll_interval_seconds)

        raise TimeoutError(
            f"transaction {transaction_id} did not reach terminal state "
            f"within {self.config.poll_max_attempts} polls"
        )
