# 首个具体项目候选研究

核验时间：**2026-11-06T11:47:19+00:00**（北京时间 2026-11-06 19:47）。本轮仅核实 **2 个项目**：Gensyn RL Swarm、Psyche / NousNet。来源限官方项目文档、官方代码仓库及交易所一手公告。

**结论：未选出满足当前目标的首个项目。** Gensyn 的官方训练 swarm 已暂停，而且已有代币发行及现货上市资料。Psyche / NousNet 的技术路线有可固定版本的官方文档，但当前可加入轮次、用户资格、具体奖励资产与未开盘状态缺乏足够证据。不能用这两项研究宣称 P3 的具体项目闭环已完成。

本轮只读取网页及仓库文档、元数据；未调用模型服务 API，未下载或执行项目软件，未注册账号、创建钱包、签名、付款、加入训练或领取奖励。本文件不构成项目参与授权。

## 候选结论

| 候选 | 当前参与判断 | 奖励与交易状态 | 处理 |
| --- | --- | --- | --- |
| Gensyn RL Swarm | 官方明确暂停，无官方 swarm；社区自建 swarm 不等于原官方活动开放 | 官方代币文档记录 2026 年 4 月分发；Bitget 有 AIGENSYN 现货上市公告 | 排除首个“未开盘且当前可参与”项目；保留为过期机会识别案例 |
| Psyche / NousNet | 代码和文档存在，但未核实当前具体 run ID、管理员及授权条件；公开运行面板本轮访问超时 | 奖励按训练轮次配置，可能无奖励；未核实官方原生资产、兑换承诺或市场状态 | 待核验；不得将“未找到交易证据”写为未开盘 |

## 1. Gensyn RL Swarm

### 开放状态及身份

官方文档标题已标注 RL Swarm 暂停，并明确没有正在运行的官方 swarm；官方仓库首页也有同样通知。正文仍保留 CodeZero 活跃环境及启动教程等旧描述，本次以明确的暂停通知为当前参与判断依据。社区自行部署的 swarm 需要独立核验活动身份、规则和贡献记录，不能承接原活动资格。[官方状态页](https://docs.gensyn.ai/testnet/rl-swarm)、[官方仓库](https://github.com/gensyn-ai/rl-swarm)。

### 硬件与资格

官方入门页给出的历史运行条件：64 位 ARM64/x86 CPU 和至少 32 GB 内存，或官方支持的 NVIDIA 3090、4090、5090、A100、H100；Python 3.10–3.13，Docker、Git、稳定网络。Windows 路线经 WSL 2；Linux 指向 Ubuntu 22.04+。不能据此填出未公布的最低磁盘、实际功耗、电费或稳定算力。[官方入门文档](https://docs.gensyn.ai/testnet/rl-swarm/getting-started)。

登录涉及测试网身份及本地 peer 身份文件。入门页称需要 Hugging Face 写入 token，而仓库 README 将其描述为上传模型时的选项；若以后恢复，必须以选定版本和活动规则消除这一差异。当前不采集账号或任何凭据。

### 贡献验证与奖励

官方说明可将 peer 与链上身份关联，通过测试网记录、训练进度及模型上传记录核对贡献。排行榜活动分数和训练奖励字段不能直接解释为可提现收益，历史记录也不能证明新加入仍获认可。[RL Swarm 官方说明](https://docs.gensyn.ai/testnet/rl-swarm)。

Gensyn 官网链接到其 Foundation；Foundation 代币页将初始分发列为 **2026 年 4 月**，并描述已设立的代币及回购机制。Bitget 的一手公告将 AIGENSYN/USDT 现货开盘时间列为 **2026-04-29 11:00 UTC**，公告合约与 Foundation 文档的 Gensyn 主网地址一致。足以排除“尚未首次开盘”条件；这不等于本轮验证了所有地区账户当前可下单。[项目官网](https://www.gensyn.ai/)、[官方代币文档](https://docs.gensyn.network/ai-token)、[Bitget 上市公告](https://www.bitget.com/support/articles/12560603883325)。

### 版本及可校验性

本次通过官方仓库 API 读取的 `main` 指向 `286c17e5391fa3e9ebba64a8e683bb36e47376a8`，提交时间 **2026-10-28T16:59:20Z**，GitHub 返回提交签名验证为有效。这提供源码定位依据，**不是已经校验过的安装包或容器摘要**；本轮未构建、下载或验证依赖链。[分支元数据](https://api.github.com/repos/gensyn-ai/rl-swarm/branches/main)。

## 2. Psyche / NousNet

### 身份、开放状态和资格

Nous Research 官方介绍链接的 `PsycheFoundation/psyche` 仓库现重定向到 `PsycheFoundation/nousnet`。本次用 GitHub 官方连接器读取仓库内的固定版本文档，避免把无法打开的文档站搜索摘要当作已核验材料。[项目官方介绍](https://nousresearch.com/nous-psyche)、[当前官方仓库](https://github.com/PsycheFoundation/nousnet)。

快速入门说明须从轮次管理员获得 run-manager、run ID 及加入授权；创建轮次的文档又允许创建公开或私有授权。因此不能声称所有轮次都私有，也不能推断任意用户当前都可加入。应针对具体 `run_id + coordinator + authorizer + network` 核实资格。本轮没有获得可确认开放的具体轮次。[固定版本快速入门](https://github.com/PsycheFoundation/nousnet/blob/0bdb13d94a05675da93d69ffa5d4c4e5a680736c/psyche-book/src/enduser/quickstart-compute-provider.md)、[轮次与授权配置](https://github.com/PsycheFoundation/nousnet/blob/0bdb13d94a05675da93d69ffa5d4c4e5a680736c/psyche-book/src/enduser/create-run.md)。

### 硬件、软件和贡献验证

固定版本加入指南要求现代 Linux、CUDA 兼容 NVIDIA GPU、驱动、Docker Engine、NVIDIA Container Toolkit；具体显存取决于目标模型。需要 Solana 身份和 RPC/WS RPC，指南包含加入资格检查。FAQ 将 macOS 限于开发用途，AMD ROCm 仍列为规划。不能将 Windows/WSL、某款消费显卡或任意显存量自动判为兼容。[加入指南](https://github.com/PsycheFoundation/nousnet/blob/0bdb13d94a05675da93d69ffa5d4c4e5a680736c/psyche-book/src/enduser/join-run.md)、[客户端 FAQ](https://github.com/PsycheFoundation/nousnet/blob/0bdb13d94a05675da93d69ffa5d4c4e5a680736c/psyche-book/src/enduser/client-faq.md)。

配方若将来成立，应验证具体轮次的链上参与者、epoch 状态和贡献记录，再交叉检查本地训练日志、见证或检查点。2025 年官方架构文介绍 coordinator、参与者、见证和检查点的关系，但该说明不证明 2026 年 11 月存在可加入且有奖励的运行轮次。[官方架构文](https://nousresearch.com/nous-psyche)。

### 奖励、上市及版本

创建轮次文档明确支持不带 token 激励的训练；带奖励的轮次需指定 Solana token mint，并由管理员为 treasury 注资，才能按规则兑换累计点数。文档中的领取命令只证明接口设计，不能证明当前奖励余额、资产价值或领取资格。FAQ 还留有“奖励实现后”的旧措辞，必须检查具体部署及轮次规则后消除版本差异。[奖励配置](https://github.com/PsycheFoundation/nousnet/blob/0bdb13d94a05675da93d69ffa5d4c4e5a680736c/psyche-book/src/enduser/create-run.md)、[客户端 FAQ](https://github.com/PsycheFoundation/nousnet/blob/0bdb13d94a05675da93d69ffa5d4c4e5a680736c/psyche-book/src/enduser/client-faq.md)。

本次未核实 Psyche/NousNet 官方原生代币的发行或现货状态；`token_issued/cex_spot/dex_spot` 均应保留 `unknown`。Solana 的 SOL、训练轮次的奖励 mint 与所谓未来项目代币是不同对象，不可混为“可挖的新币”。

官方仓库 `main` 本次解析到 `0bdb13d94a05675da93d69ffa5d4c4e5a680736c`，提交时间 **2026-03-20T19:58:10Z**，GitHub 返回提交签名验证为有效；上文文档已按此提交读取。文档仍使用预先分发的二进制及可变容器标签，当前没有验证具体 binary SHA-256、镜像 digest 与运行轮次版本是否匹配。固定源码引用可以审阅，尚不足以发布可执行配方。[分支元数据](https://api.github.com/repos/PsycheFoundation/nousnet/branches/main)。

## P3 后续条件与配方计划边界

当前选择状态为 `NO_ELIGIBLE_PROJECT_SELECTED`，不创建或运行真实项目配方。Psyche/NousNet 仅可保留为待核验技术路线，至少补齐：

1. 当前开放的具体轮次、官方管理员和网络；确认公开授权或用户已具备加入资格。
2. 目标模型、最小显存/内存/磁盘、运行时段、RPC 与预计成本；与实际机器及用户预算匹配。
3. 奖励对象与约定交付物；如仅验证训练贡献，就明确为贡献回执，不承诺未来代币。
4. 对应源码提交、管理员发布的二进制校验值或可信容器 digest；复核配置字段差异，拒绝直接将 `latest` 当固定版本。
5. 只有在符合用户筛选目标后，才制作纯模拟步骤：资料核验 → 资源匹配 → 权限检查 → 模拟准备/训练/贡献核验/交付。无真实轮次和资格时，模拟应阻断并指出缺项，不能打印成功闭环。

## 本轮访问限制

`docs.psyche.network` 的加入指南及 FAQ、`psyche.network` 的运行面板和 legal 页面多次抓取超时；这只说明本次无法读取，不能断言项目已经关停。相关技术内容改用同一官方仓库的固定版本 Markdown。Gensyn dashboard 返回无可读正文，因此没有据其搜索摘要填入当前链上数字。尚未取得的运行现场、资产规则和二进制校验均保留未知。
