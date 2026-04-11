#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/config.yaml}"
RUNS="${RUNS:-8}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-3600}"

cd "$PROJECT_DIR"

LOGS_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOGS_DIR"

SUMMARY_LOG="$LOGS_DIR/live_8h_summary.log"
STOP_FLAG="$LOGS_DIR/STOP_LIVE_8H.flag"

log_line() {
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  local line="$ts $*"
  echo "$line" | tee -a "$SUMMARY_LOG"
}

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  echo "Python virtualenv not found: $PROJECT_DIR/.venv/bin/python" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Config file not found: $CONFIG_PATH" >&2
  exit 1
fi

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

log_line "START live test loop runs=$RUNS interval_seconds=$INTERVAL_SECONDS config=$CONFIG_PATH"

for ((i=1; i<=RUNS; i++)); do
  if [[ -f "$STOP_FLAG" ]]; then
    log_line "STOP flag detected, exiting before run=$i"
    break
  fi

  run_tag="$(date '+%Y%m%d_%H%M%S')"
  run_log="$LOGS_DIR/live_run_${i}_${run_tag}.log"
  log_line "RUN_START run=$i/$RUNS run_log=$run_log"

  if "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/main.py" --config "$CONFIG_PATH" --mode live --log-level INFO \
    2>&1 | tee -a "$run_log"; then
    log_line "RUN_END run=$i/$RUNS exit_code=0 run_log=$run_log"
  else
    exit_code=$?
    log_line "RUN_END run=$i/$RUNS exit_code=$exit_code run_log=$run_log"
    log_line "ABORT non-zero exit code detected run=$i exit_code=$exit_code"
    break
  fi

  if (( i < RUNS )); then
    log_line "SLEEP seconds=$INTERVAL_SECONDS before next run"
    sleep "$INTERVAL_SECONDS"
  fi
done

log_line "END live test loop"

