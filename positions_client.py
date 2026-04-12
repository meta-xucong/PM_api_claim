from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models import AppConfig, Position


class ClaimTaskType(StrEnum):
    CTF = "CTF"
    NEGATIVE_RISK = "NEGATIVE_RISK"


@dataclass(frozen=True)
class ClaimTask:
    condition_id: str
    task_type: ClaimTaskType
    yes_token_id: int | None = None
    no_token_id: int | None = None


@dataclass
class ClaimableResult:
    claim_tasks: list[ClaimTask]
    skipped_negative_risk_condition_ids: list[str]


def _new_retry(total: int, backoff: float) -> Retry:
    return Retry(
        total=total,
        connect=total,
        read=total,
        status=total,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )


def _extract_yes_no_token_ids(group: list[Position]) -> tuple[int | None, int | None]:
    yes_token_id: int | None = None
    no_token_id: int | None = None

    for position in group:
        token_id = position.asset_token_id
        if token_id is None:
            continue
        outcome = (position.outcome or "").strip().lower()
        if outcome == "yes" and yes_token_id is None:
            yes_token_id = token_id
        elif outcome == "no" and no_token_id is None:
            no_token_id = token_id
        elif outcome not in {"yes", "no"}:
            if position.outcomeIndex == 0 and yes_token_id is None:
                yes_token_id = token_id
            elif position.outcomeIndex == 1 and no_token_id is None:
                no_token_id = token_id

    return yes_token_id, no_token_id


def extract_claimable_tasks(
    positions: Iterable[Position], *, enable_negative_risk_claim: bool
) -> ClaimableResult:
    groups: dict[str, list[Position]] = {}
    for position in positions:
        groups.setdefault(position.conditionId.lower(), []).append(position)

    claim_tasks: list[ClaimTask] = []
    skipped_nr: set[str] = set()

    for condition_id, group in groups.items():
        redeemable_group = [
            position
            for position in group
            if position.redeemable and position.numeric_size > 0
        ]
        if not redeemable_group:
            continue

        is_negative_risk = any(position.is_negative_risk for position in redeemable_group)
        if is_negative_risk:
            if not enable_negative_risk_claim:
                skipped_nr.add(condition_id)
                continue

            yes_token_id, no_token_id = _extract_yes_no_token_ids(redeemable_group)
            if yes_token_id is None and no_token_id is None:
                skipped_nr.add(condition_id)
                continue

            claim_tasks.append(
                ClaimTask(
                    condition_id=condition_id,
                    task_type=ClaimTaskType.NEGATIVE_RISK,
                    yes_token_id=yes_token_id,
                    no_token_id=no_token_id,
                )
            )
            continue

        claim_tasks.append(
            ClaimTask(condition_id=condition_id, task_type=ClaimTaskType.CTF)
        )

    claim_tasks.sort(key=lambda item: item.condition_id)
    return ClaimableResult(
        claim_tasks=claim_tasks,
        skipped_negative_risk_condition_ids=sorted(skipped_nr),
    )


class PositionsClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.base_url = config.data_api_url.rstrip("/")
        self.session = requests.Session()
        retry = _new_retry(config.request_retry_total, config.request_retry_backoff_seconds)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def fetch_positions(self, user_address: str) -> list[Position]:
        all_positions: list[Position] = []
        limit = self.config.positions_page_limit
        offset = 0

        while True:
            params = {
                "user": user_address,
                "redeemable": "true",
                "sizeThreshold": 0,
                "limit": limit,
                "offset": offset,
            }
            response = self.session.get(
                f"{self.base_url}/positions",
                params=params,
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("/positions response must be a JSON list")

            page_items = [Position.model_validate(item) for item in payload]
            all_positions.extend(page_items)

            if len(page_items) < limit:
                break
            offset += limit

        return all_positions

    def find_claimable_conditions(self, user_address: str) -> ClaimableResult:
        positions = self.fetch_positions(user_address)
        return extract_claimable_tasks(
            positions, enable_negative_risk_claim=self.config.enable_negative_risk_claim
        )
