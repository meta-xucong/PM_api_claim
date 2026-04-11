# PM_api_claim

Polymarket 多账号自动 claim 脚本（Python 3.11+，Relayer API，SAFE 模式）。

## 功能

- 多账号串行执行
- 自动发现可 claim 条件（无可 claim 自动跳过）
- 三种模式：`dry-run` / `build-only` / `live`
- 支持 systemd timer 每小时执行

## Debian VPS 一键部署（支持目录已存在）

默认路径：`/home/trader/polymarket_api`

下面命令可重复执行，兼容：

- 目录不存在
- 目录已存在且是 git 仓库（包括 `.git` 存在但没有 `origin`）
- 目录已存在但不是 git 仓库

```bash
sudo TARGET_DIR=/home/trader/polymarket_api \
REPO_URL=https://github.com/meta-xucong/PM_api_claim.git \
BRANCH=main \
bash -c '
set -e
mkdir -p "$TARGET_DIR"
git config --global --add safe.directory "$TARGET_DIR" || true

if [ -d "$TARGET_DIR/.git" ]; then
  if git -C "$TARGET_DIR" remote get-url origin >/dev/null 2>&1; then
    git -C "$TARGET_DIR" remote set-url origin "$REPO_URL"
  else
    git -C "$TARGET_DIR" remote add origin "$REPO_URL"
  fi
  git -C "$TARGET_DIR" fetch origin "$BRANCH"
  git -C "$TARGET_DIR" checkout -B "$BRANCH" "origin/$BRANCH" --force
else
  if [ -n "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]; then
    git -C "$TARGET_DIR" init
    git config --global --add safe.directory "$TARGET_DIR" || true
    git -C "$TARGET_DIR" remote add origin "$REPO_URL" 2>/dev/null || git -C "$TARGET_DIR" remote set-url origin "$REPO_URL"
    git -C "$TARGET_DIR" fetch origin "$BRANCH"
    git -C "$TARGET_DIR" checkout -B "$BRANCH" "origin/$BRANCH" --force
  else
    git clone --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR"
  fi
fi

chmod +x "$TARGET_DIR/bootstrap_deploy.sh"
TARGET_DIR="$TARGET_DIR" REPO_URL="$REPO_URL" BRANCH="$BRANCH" bash "$TARGET_DIR/bootstrap_deploy.sh"
'
```

## 部署后流程

1. 填配置

```bash
nano /home/trader/polymarket_api/.env
nano /home/trader/polymarket_api/config.yaml
```

2. 手动 dry-run 校验

```bash
cd /home/trader/polymarket_api
set -a; source .env; set +a
.venv/bin/python main.py --config config.yaml --mode dry-run --log-level INFO
```

3. 启动定时任务（每小时）

```bash
sudo systemctl enable --now polymarket-claim.timer
sudo systemctl status polymarket-claim.timer --no-pager
```

4. 查看日志

```bash
journalctl -u polymarket-claim.service -n 200 --no-pager
```

5. 立刻执行一次（不等整点）

```bash
sudo systemctl start polymarket-claim.service
journalctl -u polymarket-claim.service -n 200 --no-pager
```

