from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Iterable
from urllib.parse import quote

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
    ctf_index_sets: tuple[int, ...] | None = None
    route_source_slug: str | None = None


@dataclass
class ClaimableResult:
    claim_tasks: list[ClaimTask]
    skipped_negative_risk_condition_ids: list[str]
    unroutable_condition_ids: list[str]
    route_errors: dict[str, str]


@dataclass(frozen=True)
class ResolvedConditionRoute:
    task_type: ClaimTaskType
    yes_token_id: int | None = None
    no_token_id: int | None = None
    ctf_index_sets: tuple[int, ...] | None = None
    source_slug: str | None = None


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


def _parse_list_field(value: Any, *, field_name: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    raise ValueError(f"{field_name} must be a list or JSON-encoded list")


def _slug_from_group(group: list[Position]) -> str:
    for position in group:
        slug = (position.slug or "").strip()
        if slug:
            return slug
    raise ValueError("position group missing slug, cannot resolve canonical market metadata")


def extract_claimable_tasks(
    positions: Iterable[Position],
    *,
    enable_negative_risk_claim: bool,
    route_resolver: Callable[[str, list[Position]], ResolvedConditionRoute],
) -> ClaimableResult:
    groups: dict[str, list[Position]] = {}
    for position in positions:
        groups.setdefault(position.conditionId.lower(), []).append(position)

    claim_tasks: list[ClaimTask] = []
    skipped_nr: set[str] = set()
    unroutable: set[str] = set()
    route_errors: dict[str, str] = {}

    for condition_id, group in groups.items():
        redeemable_group = [
            position
            for position in group
            if position.redeemable and position.numeric_size > 0
        ]
        if not redeemable_group:
            continue

        try:
            route = route_resolver(condition_id, redeemable_group)
        except Exception as exc:
            unroutable.add(condition_id)
            route_errors[condition_id] = str(exc)
            continue

        if route.task_type == ClaimTaskType.NEGATIVE_RISK:
            if not enable_negative_risk_claim:
                skipped_nr.add(condition_id)
                continue

            if route.yes_token_id is None or route.no_token_id is None:
                unroutable.add(condition_id)
                route_errors[condition_id] = "negative risk route missing canonical yes/no token ids"
                continue

            claim_tasks.append(
                ClaimTask(
                    condition_id=condition_id,
                    task_type=ClaimTaskType.NEGATIVE_RISK,
                    yes_token_id=route.yes_token_id,
                    no_token_id=route.no_token_id,
                    route_source_slug=route.source_slug,
                )
            )
            continue

        if not route.ctf_index_sets:
            unroutable.add(condition_id)
            route_errors[condition_id] = "ctf route missing canonical index sets"
            continue

        claim_tasks.append(
            ClaimTask(
                condition_id=condition_id,
                task_type=ClaimTaskType.CTF,
                ctf_index_sets=route.ctf_index_sets,
                route_source_slug=route.source_slug,
            )
        )

    claim_tasks.sort(key=lambda item: item.condition_id)
    return ClaimableResult(
        claim_tasks=claim_tasks,
        skipped_negative_risk_condition_ids=sorted(skipped_nr),
        unroutable_condition_ids=sorted(unroutable),
        route_errors=route_errors,
    )


class PositionsClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.base_url = config.data_api_url.rstrip("/")
        self.gamma_base_url = config.gamma_api_url.rstrip("/")
        self.session = requests.Session()
        retry = _new_retry(config.request_retry_total, config.request_retry_backoff_seconds)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._market_cache: dict[str, dict[str, Any]] = {}

    def _fetch_market_by_slug(self, slug: str) -> dict[str, Any]:
        if slug in self._market_cache:
            return self._market_cache[slug]

        response = self.session.get(
            f"{self.gamma_base_url}/markets/slug/{quote(slug, safe='')}",
            timeout=self.config.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected market payload for slug={slug}: expected object")
        self._market_cache[slug] = payload
        return payload

    def _resolve_route(self, condition_id: str, group: list[Position]) -> ResolvedConditionRoute:
        slug = _slug_from_group(group)
        market = self._fetch_market_by_slug(slug)

        market_condition_id = str(market.get("conditionId", "")).strip().lower()
        if market_condition_id != condition_id:
            raise ValueError(
                f"slug={slug} condition mismatch: expected {condition_id}, got {market_condition_id}"
            )

        outcomes_raw = _parse_list_field(market.get("outcomes"), field_name="outcomes")
        token_ids_raw = _parse_list_field(market.get("clobTokenIds"), field_name="clobTokenIds")
        outcomes = [str(item).strip() for item in outcomes_raw if str(item).strip()]
        token_ids = [int(str(item).strip()) for item in token_ids_raw]
        if len(outcomes) != len(token_ids):
            raise ValueError(
                f"slug={slug} outcomes/tokenIds length mismatch: {len(outcomes)} vs {len(token_ids)}"
            )
        if len(outcomes) < 2:
            raise ValueError(f"slug={slug} invalid outcome count: {len(outcomes)}")
        if len(outcomes) > 16:
            raise ValueError(f"slug={slug} unexpected outcome count: {len(outcomes)}")

        if bool(market.get("negRisk")):
            mapping = {
                outcome.lower(): token_id
                for outcome, token_id in zip(outcomes, token_ids, strict=False)
            }
            yes_token_id = mapping.get("yes")
            no_token_id = mapping.get("no")
            if yes_token_id is None or no_token_id is None:
                raise ValueError(
                    f"slug={slug} negRisk market missing explicit Yes/No outcomes; "
                    "cannot build canonical [yes,no] claim amounts"
                )
            return ResolvedConditionRoute(
                task_type=ClaimTaskType.NEGATIVE_RISK,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                source_slug=slug,
            )

        return ResolvedConditionRoute(
            task_type=ClaimTaskType.CTF,
            ctf_index_sets=tuple(1 << i for i in range(len(outcomes))),
            source_slug=slug,
        )

    def fetch_positions(self, user_address: str) -> list[Position]:
        all_positions: list[Position] = []
        limit = self.config.positions_page_limit
        if limit <= 0:
            raise ValueError("positions_page_limit must be > 0")
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
            positions,
            enable_negative_risk_claim=self.config.enable_negative_risk_claim,
            route_resolver=self._resolve_route,
        )
