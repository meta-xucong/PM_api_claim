#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${TARGET_DIR:-/home/trader/polymarket_api}"
REPO_URL="${REPO_URL:-https://github.com/meta-xucong/PM_api_claim.git}"
BRANCH="${BRANCH:-main}"

need_root_install() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "This step needs root privileges to install dependencies. Re-run with sudo."
    exit 1
  fi
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  need_root_install
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y git
}

ensure_git_safe_directory() {
  if [[ ! -d "$TARGET_DIR" ]]; then
    return 0
  fi

  local abs_target
  if abs_target="$(realpath "$TARGET_DIR" 2>/dev/null)"; then
    :
  else
    abs_target="$TARGET_DIR"
  fi

  git config --global --add safe.directory "$abs_target" || true
}

ensure_origin_remote() {
  if git -C "$TARGET_DIR" remote get-url origin >/dev/null 2>&1; then
    git -C "$TARGET_DIR" remote set-url origin "$REPO_URL"
  else
    git -C "$TARGET_DIR" remote add origin "$REPO_URL"
  fi
}

sync_repo() {
  ensure_git_safe_directory

  if [[ -d "$TARGET_DIR/.git" ]]; then
    ensure_origin_remote
    git -C "$TARGET_DIR" fetch origin "$BRANCH"
    git -C "$TARGET_DIR" checkout -B "$BRANCH" "origin/$BRANCH" --force
    return 0
  fi

  if [[ -d "$TARGET_DIR" ]] && [[ -n "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]]; then
    echo "Target path exists and is not a git repo, initializing in place: $TARGET_DIR"
    git -C "$TARGET_DIR" init
    ensure_origin_remote
    git -C "$TARGET_DIR" fetch origin "$BRANCH"
    git -C "$TARGET_DIR" checkout -B "$BRANCH" "origin/$BRANCH" --force
    return 0
  fi

  mkdir -p "$(dirname "$TARGET_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR"
}

run_install_setup() {
  cd "$TARGET_DIR"
  [[ -f .env ]] || cp .env.example .env
  [[ -f config.yaml ]] || cp config.example.yaml config.yaml

  chmod +x deploy_systemd_hourly.sh
  PROJECT_DIR="$TARGET_DIR" \
  CONFIG_PATH="$TARGET_DIR/config.yaml" \
  ENV_FILE_PATH="$TARGET_DIR/.env" \
  bash "$TARGET_DIR/deploy_systemd_hourly.sh"
}

ensure_git
sync_repo
run_install_setup

cat <<EOF
Bootstrap deployment completed.
Config files:
  $TARGET_DIR/.env
  $TARGET_DIR/config.yaml
After editing configs, start timer:
  systemctl enable --now polymarket-claim.timer
EOF
