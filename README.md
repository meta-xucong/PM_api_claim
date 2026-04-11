# PM_api_claim

Polymarket 多账号自动 claim 脚本（Python 3.11+，Relayer API，SAFE 模式）。

## 功能

- 多账号串行执行
- 自动发现可 claim 条件（无可 claim 自动跳过）
- 三种模式：`dry-run` / `build-only` / `live`
- 支持 systemd timer 每小时执行

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config.example.yaml config.yaml
```

填写：

- `.env`（私钥、Relayer API Key）
- `config.yaml`（SAFE 地址、Signer 地址、API Address 等）

手动运行：

```bash
python main.py --config config.yaml --mode dry-run
python main.py --config config.yaml --mode build-only
python main.py --config config.yaml --mode live
```

## Debian VPS 一键部署（支持目录已存在）

默认路径：`/home/trader/polymarket_api`

说明：下面命令可重复执行。目录不存在时自动 clone，目录已存在且是 git 仓库时自动 pull 更新并继续部署。

```bash
sudo TARGET_DIR=/home/trader/polymarket_api \
REPO_URL=https://github.com/meta-xucong/PM_api_claim.git \
BRANCH=main \
bash -c '
set -e
if [ -d "$TARGET_DIR/.git" ]; then
  git -C "$TARGET_DIR" fetch origin "$BRANCH"
  git -C "$TARGET_DIR" checkout "$BRANCH"
  git -C "$TARGET_DIR" pull --ff-only origin "$BRANCH"
else
  mkdir -p "$(dirname "$TARGET_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR"
fi
chmod +x "$TARGET_DIR/bootstrap_deploy.sh"
TARGET_DIR="$TARGET_DIR" REPO_URL="$REPO_URL" BRANCH="$BRANCH" bash "$TARGET_DIR/bootstrap_deploy.sh"
'
```

`bootstrap_deploy.sh` 会自动：

- 安装/补齐依赖（包含 Debian 上 `python3.x-venv` 场景）
- 创建虚拟环境并安装 Python 包
- 写入 systemd service/timer 文件（默认不自动启动）
- 自动生成 `.env` / `config.yaml`（若不存在）

## 部署后推荐流程

1. 填配置

```bash
nano /home/trader/polymarket_api/.env
nano /home/trader/polymarket_api/config.yaml
```

2. 手动 dry-run 验证配置

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

4. 查看执行日志

```bash
journalctl -u polymarket-claim.service -n 200 --no-pager
```

5. 立刻执行一次（不等整点）

```bash
sudo systemctl start polymarket-claim.service
journalctl -u polymarket-claim.service -n 200 --no-pager
```

提示：`enable --now polymarket-claim.timer` 会立刻启动 timer，但不会立即执行 service；默认在下一整点触发。

