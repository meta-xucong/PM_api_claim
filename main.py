from __future__ import annotations

import argparse
import logging
import sys

from claim_runner import ClaimRunner
from config_loader import load_config
from models import RunMode


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Polymarket multi-account proxy auto-claim runner"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML/JSON config file",
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default=RunMode.DRY_RUN.value,
        help="Execution mode: dry-run | build-only | live",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    args = _parse_args()
    _setup_logging(args.log_level)

    config = load_config(args.config)
    mode = RunMode(args.mode)
    runner = ClaimRunner(config=config, mode=mode)
    summary = runner.run()

    logging.info(
        "summary total_accounts=%s processed_accounts=%s total_conditions=%s "
        "submitted=%s confirmed=%s failed=%s mode=%s",
        summary.total_accounts,
        summary.processed_accounts,
        summary.total_conditions,
        summary.submitted_transactions,
        summary.confirmed_transactions,
        summary.failed_transactions,
        mode.value,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
