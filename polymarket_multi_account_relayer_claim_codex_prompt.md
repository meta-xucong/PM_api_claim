# Polymarket 多账户自动 Claim（Relayer API Key / Python / PROXY）Codex 精简提示词

请为 Polymarket 编写一个 **Python 后端脚本**，用于 **多账户自动 claim（redeem）**，严格遵照官方文档和官方仓库实现，不要自行发明签名格式。

## 目标与边界

- 使用 **Relayer API Key + Relayer API 直连**。
- **不要使用 Builder API Keys**。
- **不要把 `py-builder-relayer-client` 作为主实现路径**；它只能作为官方参考实现，用于移植 PROXY 编码与签名逻辑。
- 仅实现 **PROXY 模式**，不实现 SAFE。
- **V1 只处理普通 CTF redeem**：`negativeRisk=false` 的仓位。
- `negativeRisk=true` 的仓位先 **跳过并记录日志**。
- 链 ID 固定 **137（Polygon mainnet）**。

## 数据发现逻辑

1. 使用 Polymarket **Data API `/positions`** 查询仓位。
2. 只筛选：
   - `redeemable = true`
   - `negativeRisk = false`
   - `size > 0`
3. 按 **`conditionId` 去重**。
4. 每个账户、每个 `conditionId` 只发起 **1 笔 redeem**。

## 合约调用逻辑

对每个可 redeem 的 `conditionId`：

### 第一步：构造普通 CTF `redeemPositions()` calldata

调用参数固定：

- `collateralToken = USDC.e`
- `parentCollectionId = 32字节全零`
- `conditionId = 当前 conditionId`
- `indexSets = [1, 2]`

注意：
- 不要添加 amount 参数。
- 该调用会赎回该 `conditionId` 下当前账户的全部可赎回余额。

### 第二步：把上面的调用包装进 ProxyFactory 的 `proxy(tuple[] calls)`

外层 `calls` 数组里只放 1 个调用对象：

- `typeCode = Call`
- `to = CTF 合约地址`
- `value = 0`
- `data = 上一步生成的 redeemPositions calldata`

## PROXY 编码与签名要求

不要自己设计签名逻辑，必须按官方 `builder-relayer-client` 仓库移植到 Python：

- `src/builder/proxy.ts`
- `src/encode/proxy.ts`
- `src/builder/derive.ts`
- `src/constants/index.ts`
- `src/config/index.ts`
- `src/abis/proxyFactory.ts`
- `tests/signatures/index.test.ts`

必须实现：

1. Polygon 主网 `ProxyFactory` / `RelayHub` 常量配置。
2. `deriveProxyWallet` 逻辑。
3. `proxy(tuple[] calls)` 的 ABI 编码。
4. 官方 `createStructHash(...)` 的同等 Python 实现。
5. 使用 signer 私钥对 struct hash 做消息签名。
6. 生成符合官方格式的：
   - `signature`
   - `signatureParams`
   - `type = "PROXY"`

## Relayer API 调用要求

### 认证头

请求头必须带：

- `RELAYER_API_KEY`
- `RELAYER_API_KEY_ADDRESS`

### 交易提交流程

1. 先调用 **`/relay-payload`** 获取：
   - `relayer address`
   - `nonce`
2. 用该返回值参与 PROXY 签名。
3. 调用 **`/submit`** 提交交易。
4. 调用 **`/transaction?id=...`** 轮询状态，直到终态。

### 成功 / 失败判定

- `STATE_CONFIRMED` => 成功
- `STATE_FAILED` => 失败
- `STATE_INVALID` => 失败
- `STATE_NEW / STATE_EXECUTED / STATE_MINED` => 继续轮询

## 多账户设计要求

每个账户配置至少包含：

- `account_name`
- `enabled`
- `signer_private_key`
- `signer_address`
- `proxy_wallet`
- `relayer_api_key`
- `relayer_api_key_address`

执行策略：

- **账户级串行执行**
- **账户内 condition 串行执行**
- 每发 1 笔交易，都要等到终态后再执行下一笔
- 先做稳定性优先，不做同一 signer 的并发 nonce 抢占

## 代码结构要求

请先按下面的文件结构设计：

- `config_loader.py`
- `models.py`
- `positions_client.py`
- `calldata_builder.py`
- `proxy_encoder.py`
- `proxy_signer.py`
- `relayer_client.py`
- `claim_runner.py`
- `main.py`

## 运行模式要求

至少支持三种模式：

### 1. `dry-run`
- 只查询并打印每个账户可 claim 的 `conditionId`
- 不构造提交请求
- 不发送交易

### 2. `build-only`
- 构造完整提交体
- 打印将要提交的 payload
- 不真正调用 `/submit`

### 3. `live`
- 真正提交交易
- 轮询直到终态

## 日志要求

日志中必须包含：

- `account_name`
- `signer_address`
- `proxy_wallet`
- `conditionId`
- `transactionID`
- `transactionHash`
- `final_state`

禁止：

- 打印私钥
- 把 API key 写入日志
- 在代码中硬编码私钥或 key

## 测试要求

必须包含至少以下测试：

1. **官方 proxy 黄金向量签名测试**
   - 复刻 `tests/signatures/index.test.ts` 的公开测试样例
   - 验证 Python 实现生成的签名与官方预期完全一致

2. **redeem calldata 编码测试**
   - 验证普通 CTF `redeemPositions()` 编码结果正确

3. **positions 去重测试**
   - 多条同 `conditionId` 仓位时，只生成 1 个 claim 任务

## 交付顺序要求

不要一开始直接输出完整代码。

请按这个顺序交付：

### 第 1 步
先输出：
- 总体设计说明
- 文件树
- 数据流说明
- 关键函数签名
- 风险点说明
- 测试计划

### 第 2 步
再输出：
- `dry-run` 版本代码
- 单元测试骨架

### 第 3 步
最后再补：
- `build-only`
- `live`
- 轮询与日志
- 错误处理

## 额外要求

- 代码要可维护、模块化、类型清晰。
- 使用 Python 3.11+。
- 优先使用 `web3.py`、`requests`、`pydantic`、`pytest`。
- 所有常量集中管理。
- 所有网络请求都加超时、重试、错误处理。
- 所有提交前都先做参数校验。
- 对官方仓库移植的关键逻辑，增加注释说明其来源与用途。
