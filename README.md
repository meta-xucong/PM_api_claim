# PM_api_claim

Polymarket 多账号自动 claim 脚本（Python 3.11+，Relayer API，SAFE 模式）。

## 功能

- 多账号串行执行
- 自动发现可 claim 条件（无可 claim 自动跳过）
- 三种模式：
  - `dry-run`
  - `build-only`
  - `live`
- 支持定时运行（systemd timer 每小时执行）

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config.example.yaml config.yaml
```

然后填好：

- `.env`（私钥、Relayer API Key）
- `config.yaml`（地址、账号、合约配置）

## 运行

```bash
python main.py --config config.yaml --mode dry-run
python main.py --config config.yaml --mode build-only
python main.py --config config.yaml --mode live
```

## 一键部署到 Debian VPS（systemd 每小时执行）

> 先把下面命令里的 `<GITHUB_USER>` 改成你的 GitHub 用户名。
> `deploy_systemd_hourly.sh` 会自动检查并安装缺失依赖（`python3` / `python3-venv` / `systemd`）。

```bash
sudo apt update && sudo apt install -y git && \
sudo git clone https://github.com/<GITHUB_USER>/PM_api_claim.git /opt/PM_api_claim && \
cd /opt/PM_api_claim && \
cp .env.example .env && cp config.example.yaml config.yaml && \
chmod +x deploy_systemd_hourly.sh && \
sudo PROJECT_DIR=/opt/PM_api_claim CONFIG_PATH=/opt/PM_api_claim/config.yaml ENV_FILE_PATH=/opt/PM_api_claim/.env bash /opt/PM_api_claim/deploy_systemd_hourly.sh
```

部署后查看：

```bash
systemctl status polymarket-claim.timer --no-pager
journalctl -u polymarket-claim.service -n 200 --no-pager
```
