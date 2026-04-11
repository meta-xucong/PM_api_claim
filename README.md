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

## Debian VPS 一键部署（默认只安装，不自动启动）

```bash
sudo apt update && sudo apt install -y git && \
sudo git clone https://github.com/meta-xucong/PM_api_claim.git /opt/PM_api_claim && \
cd /opt/PM_api_claim && \
cp .env.example .env && cp config.example.yaml config.yaml && \
chmod +x deploy_systemd_hourly.sh && \
sudo PROJECT_DIR=/opt/PM_api_claim CONFIG_PATH=/opt/PM_api_claim/config.yaml ENV_FILE_PATH=/opt/PM_api_claim/.env bash /opt/PM_api_claim/deploy_systemd_hourly.sh
```

说明：

- 部署脚本会自动补齐 Debian 依赖（包括 `python3.x-venv`，例如 `python3.12-venv`）。
- 如果目录已存在，改用更新流程：`cd /opt/PM_api_claim && sudo git pull`
- 如果你是 fork 仓库，请把 clone URL 换成你自己的，不要使用 `<...>` 占位符。

## 部署后推荐流程

1. 填配置

```bash
nano /opt/PM_api_claim/.env
nano /opt/PM_api_claim/config.yaml
```

2. 手动 dry-run 验证配置

```bash
cd /opt/PM_api_claim
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

提示：`enable --now polymarket-claim.timer` 会立刻启动 timer 本身，但不会立即跑 service；默认会在下一整点触发。
