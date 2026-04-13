from __future__ import annotations

import json
import random
from pathlib import Path

import claim_runner as claim_runner_module
from claim_runner import ClaimRunner, GracefulStopRequested
from models import AppConfig, RunMode


def _build_live_config(state_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "enable_live_hourly_jitter": False,
            "rotation_state_path": str(state_path),
            "accounts": [
                {
                    "account_name": "a1",
                    "enabled": True,
                    "signer_private_key": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
                    "signer_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                    "proxy_wallet": "0x8ba1f109551bD432803012645Ac136ddd64DBA72",
                    "relayer_api_key": "dummy",
                    "relayer_api_key_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                },
                {
                    "account_name": "a2",
                    "enabled": True,
                    "signer_private_key": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
                    "signer_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                    "proxy_wallet": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
                    "relayer_api_key": "dummy",
                    "relayer_api_key_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
                },
            ],
        }
    )


def test_live_rotation_picks_without_repetition_per_round(tmp_path: Path) -> None:
    state_path = tmp_path / "strategy_state.json"
    config = _build_live_config(state_path)
    runner = ClaimRunner(config=config, mode=RunMode.LIVE)
    runner._rng = random.Random(7)

    executed: list[str] = []

    def fake_run_account(account, summary):  # type: ignore[no-untyped-def]
        executed.append(account.account_name)

    runner._run_account = fake_run_account  # type: ignore[method-assign]

    summary1 = runner.run()
    summary2 = runner.run()

    assert summary1.processed_accounts == 1
    assert summary2.processed_accounts == 1
    assert len(executed) == 2
    assert set(executed) == {"a1", "a2"}

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["round_number"] == 2
    assert sorted(persisted["remaining_accounts"]) == ["a1", "a2"]


def test_live_hourly_jitter_delay_is_second_precision(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config = _build_live_config(Path("logs/test_strategy_state.json"))
    config.enable_live_hourly_jitter = True
    config.live_hourly_jitter_seconds = 600
    runner = ClaimRunner(config=config, mode=RunMode.LIVE)

    class _FakeRng:
        @staticmethod
        def randint(_a: int, _b: int) -> int:
            return 137

    runner._rng = _FakeRng()  # type: ignore[assignment]

    sleeps: list[int] = []
    monkeypatch.setattr(claim_runner_module.time, "time", lambda: 1710000000)
    monkeypatch.setattr(claim_runner_module.time, "sleep", lambda sec: sleeps.append(sec))

    jitter, delay = runner._apply_live_hourly_jitter()
    assert jitter == 137
    assert delay == 137
    assert sleeps == [137]


def test_live_hourly_jitter_negative_runs_before_next_top(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    config = _build_live_config(Path("logs/test_strategy_state.json"))
    config.enable_live_hourly_jitter = True
    config.live_hourly_jitter_seconds = 600
    runner = ClaimRunner(config=config, mode=RunMode.LIVE)

    class _FakeRng:
        @staticmethod
        def randint(_a: int, _b: int) -> int:
            return -120

    runner._rng = _FakeRng()  # type: ignore[assignment]

    sleeps: list[int] = []
    monkeypatch.setattr(claim_runner_module.time, "time", lambda: 1710000000)
    monkeypatch.setattr(claim_runner_module.time, "sleep", lambda sec: sleeps.append(sec))

    jitter, delay = runner._apply_live_hourly_jitter()
    assert jitter == -120
    assert delay == 3480
    assert sleeps == [3480]


def test_live_interrupted_run_releases_lock_and_does_not_advance_rotation(tmp_path: Path) -> None:
    state_path = tmp_path / "strategy_state.json"
    lock_path = Path(str(state_path) + ".lock")
    config = _build_live_config(state_path)
    runner = ClaimRunner(config=config, mode=RunMode.LIVE)
    runner._rng = random.Random(1)

    def interrupted_run_account(_account, _summary):  # type: ignore[no-untyped-def]
        raise GracefulStopRequested("received SIGTERM")

    runner._run_account = interrupted_run_account  # type: ignore[method-assign]
    summary = runner.run()

    assert summary.processed_accounts == 1
    assert not lock_path.exists()
    assert not state_path.exists()
