#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-polymarket-claim}"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/config.yaml}"
ENV_FILE_PATH="${ENV_FILE_PATH:-$PROJECT_DIR/.env}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_USER="${RUN_USER:-${SUDO_USER:-$(id -un)}}"
AUTO_START="${AUTO_START:-0}"

install_debian_deps_if_needed() {
  local missing=()

  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  # shellcheck disable=SC2015
  python3 -m venv --help >/dev/null 2>&1 || missing+=("python3-venv")
  command -v systemctl >/dev/null 2>&1 || missing+=("systemd")

  if [[ ${#missing[@]} -eq 0 ]]; then
    return 0
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Missing dependencies: ${missing[*]}"
    echo "Auto install is only supported on Debian/Ubuntu (apt-get)."
    exit 1
  fi

  echo "Installing missing dependencies: ${missing[*]}"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
}

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Config file not found: $CONFIG_PATH"
  echo "Create it first (you can copy config.example.yaml)."
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root (or with sudo)."
  exit 1
fi

install_debian_deps_if_needed

echo "PROJECT_DIR=$PROJECT_DIR"
echo "CONFIG_PATH=$CONFIG_PATH"
echo "ENV_FILE_PATH=$ENV_FILE_PATH"
echo "RUN_USER=$RUN_USER"

if [[ ! -d "$PROJECT_DIR/.venv" ]]; then
  "$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
fi

"$PROJECT_DIR/.venv/bin/python" -m ensurepip --upgrade || true
"$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TIMER_FILE="/etc/systemd/system/${SERVICE_NAME}.timer"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Polymarket Multi-account Auto Claim
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=-${ENV_FILE_PATH}
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/main.py --config ${CONFIG_PATH} --mode live --log-level INFO
Nice=10

[Install]
WantedBy=multi-user.target
EOF

cat > "$TIMER_FILE" <<EOF
[Unit]
Description=Run ${SERVICE_NAME} every hour

[Timer]
OnCalendar=hourly
Persistent=true
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload

echo "Deployment finished (install/setup only). Timer is NOT started by default."
echo "When you finish editing .env/config.yaml, start with:"
echo "  systemctl enable --now ${SERVICE_NAME}.timer"
echo "Check timer status with:"
echo "  systemctl status ${SERVICE_NAME}.timer --no-pager"
echo "Check latest logs with:"
echo "  journalctl -u ${SERVICE_NAME}.service -n 200 --no-pager"

if [[ "$AUTO_START" == "1" ]]; then
  systemctl enable --now "${SERVICE_NAME}.timer"
  echo "AUTO_START=1 detected. Timer started."
fi
