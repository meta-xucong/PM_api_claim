from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models import AppConfig, Position


@dataclass
class ClaimableResult:
    claimable_condition_ids: list[str]
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


def extract_claimable_condition_ids(positions: Iterable[Position]) -> ClaimableResult:
    claimable: dict[str, str] = {}
    skipped_nr: set[str] = set()

    for position in positions:
        condition_id = position.conditionId.lower()
        if position.is_negative_risk:
            skipped_nr.add(condition_id)
            continue

        if not position.redeemable:
            continue
        if position.numeric_size <= 0:
            continue

        claimable[condition_id] = condition_id

    return ClaimableResult(
        claimable_condition_ids=list(claimable.keys()),
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
        return extract_claimable_condition_ids(positions)

