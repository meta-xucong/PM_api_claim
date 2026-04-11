# PM_api_claim

Polymarket 多账号自动 claim 脚本（Python 3.11+，Relayer API，SAFE 模式）。

## 功能

- 多账号串行执行
- 自动发现可 claim 条件（无可 claim 自动跳过）
- 三种模式：`dry-run` / `build-only` / `live`
- 支持 systemd timer 每小时执行

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config.example.yaml config.yaml
```

然后填写：

- `.env`（私钥、Relayer API Key）
- `config.yaml`（SAFE 地址、Signer 地址、API Address 等）

## 运行

```bash
python main.py --config config.yaml --mode dry-run
python main.py --config config.yaml --mode build-only
python main.py --config config.yaml --mode live
```

## 一键部署到 Debian VPS（默认只安装，不自动启动）

直接使用下面命令（已写死当前仓库地址，避免 `<GITHUB_USER>` 占位符在 bash 里报错）：

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
- 如果你已经 clone 过仓库，先执行：`cd /opt/PM_api_claim && sudo git pull`

如果你是 fork 仓库，请把 URL 改成你自己的，但不要写 `<...>` 这种占位符格式。

## 填完配置后手动启动

```bash
sudo systemctl enable --now polymarket-claim.timer
```

## 查看状态和日志

```bash
systemctl status polymarket-claim.timer --no-pager
journalctl -u polymarket-claim.service -n 200 --no-pager
```
