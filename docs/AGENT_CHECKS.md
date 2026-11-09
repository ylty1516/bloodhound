# Agent 参与条件检查

2026-11-09 四端共同防护：新增 prospect_check_validate；四端 complete 自动校验，needs_correction 沿用原租约修正补交，报告和已知用量保留。Codex / Claude 在生成前核对实际版本及必要参数，DeepSeek API 核对新鲜且匹配的模型目录。共29工具，最新 prepared-v12；实测范围和未验收部分见 [ALL_AGENT_COMPATIBILITY.md](ALL_AGENT_COMPATIBILITY.md)。下文旧版本与工具数保留为历史记录。

2026-11-09 接入修复：选择较新的已安装Codex，沿用Windows系统代理，记录CLI来源/版本；错误分类和结构化事实约束已对齐，SHEAR真实七项报告完成。格式失败保留已知用量和私有未采纳报告。详见[NATIVE_AGENT_RECOVERY.md](NATIVE_AGENT_RECOVERY.md)。检查完成不代表项目可直接运行或安全通过。
2026-11-07更新：尝试建议采用安全优先策略，硬件不再筛除推荐；模型可在独立页面配置。以 [最新策略与模型说明](TRIAL_POLICY_AND_MODELS.md) 为准，下文旧的全条件筛选描述保留为历史实现背景。实际执行条件仍独立检查。

2026-11-06。此功能把原先的规则预检扩展为用户发起的只读 Agent 核验；不是矿工、节点或空投脚本执行器。

## 使用

实时进度与卡顿修复（2026-11-07）：Codex/Claude 原生事件流、四端 prospect_check_progress、每2秒独立同步、无变化面板保留。没有回报的阶段不补造；进程存活与实际活动分开。完整机制和证据见 [检查进度](LIVE_CHECK_PROGRESS.md)。


1. 打开本机工作台，选择项目，进入“查看与预检”。
2. 在详情顶部选择检查 Agent，点击“交给 Agent 检查”。默认选择可调用的本机 CLI。
3. 查看等待、检查中或失败原因；可以取消。完成后展开“查看七项检查与来源”，审阅项目身份、参与窗口、市场、硬件、维护时间、费用和风险。
4. Codex / Claude Code 使用各自本机 CLI 的登录状态；不读取或复制登录凭据。pi / DeepSeek Harness 使用已连接的宿主工具，任务会等待宿主领取。
5. 在已接通的 pi / DeepSeek 中可说：“领取 Prospect 中分配给你的参与条件检查，按返回的只读说明核验并回传报告。”新工具在已运行会话中可能要重新加载插件或开启新会话才能出现。

报告现会形成准备方案；project_facts 经身份、字段和来源校验后更新候选事实、解决对应研究任务，再判断提请资格。身份冲突只保存报告，unknown 不覆盖已知事实；矛盾证据保持待核验。详见 [准备流程](WORKFLOWS.md)。硬件或个人条件缺失时保持未知；任何不通过项会令综合结果为当前不适合，并解释与 Agent 原文的区别。

## 四端的实际范围

| 宿主 | 参与方式 | 本机验证 |
| --- | --- | --- |
| Codex | 网页调用 CLI，或插件工具领取/回传 | 选择桌面随附0.167.0-alpha.3.2；真实SHEAR报告和用量已保存；本轮version/help与报告修正协议验证通过 |
| Claude Code | 网页调用 CLI，或插件工具领取/回传 | 2.1.218版本和必要参数已核对；此前生成失败，修复后成功生成仍未验证 |
| pi | 扩展工具领取/回传 | 本轮真实AgentSession加载29工具并调用状态/检查队列；未做模型生成、交互CLI或恢复验收 |
| DeepSeek Harness | 插件工具领取/回传 | 本轮固定版本真实SDK加载29工具并调用检查队列；完整宿主运行时缺失，未验证完整宿主自动启动或模型生成 |

这表示四端拥有同一检查协议，不表示四端都已能从网页自动唤起。可调用状态只证明发现了 CLI；登录、联网、模型错误会单独显示。生成包：`adapters/prepared-v12/`；五处已安装/marketplace的bridge/tools与拥有权哈希已更新，未改变Hook信任设置。四端传输验证使用合成报告，不冒充真实模型生成。

## 协议和约束

检查工具为 `prospect_check_pending`、`prospect_check_request`、`prospect_check_claim`、`prospect_check_progress`、`prospect_check_validate`、`prospect_check_complete`、`prospect_check_cancel`。加上发现、待办和运行等工具，四端共29个。validate或complete返回needs_correction时，在原租约内修正报告补交，不能据此采纳事实或启动项目。

领取时使用 `codex` / `claude` / `pi` / `deepseek` 之一；返回项目/设备/个人偏好摘要、只读指令、结构化报告 schema 和私有 lease_token。必须按 schema 回传，或报告失败。lease_token 仅用于回传，不能展示给用户或写进证据文件。网页 Cookie 无权领取或提交报告，只有本机适配器的 Bearer 凭据可调用。

所有报告要求七个主题，外部事实结论要求来源；引用只能指向报告列出的公开 HTTPS 地址。输入均当作不可信资料，提示词禁止执行仓库或网页中的指令。报告格式校验不等于来源真实性的自动证明，也不等于代码安全审计。

Codex 原生检查使用临时只读会话与 live web search，关闭 shell、hooks、plugins、apps、memories 和子 agent 功能；模型与推理强度沿用“Agent与模型”设置并写入任务快照；Claude 使用 print、WebSearch/WebFetch 白名单、空 MCP、结构化输出和 user settings source，关闭 hooks、自动记忆、斜杠命令和会话持久化。保留 CLI 自管的 OAuth，不读取凭据，移除跳过 OAuth 的 bare 参数。原生进程使用独立工作目录，不保存原始 CLI 日志，只保留报告和已回报用量；凭据始终由 CLI 管理。实现依据为本机 CLI help 与 [Codex 非交互文档](https://developers.openai.com/codex/noninteractive)、[配置参考](https://developers.openai.com/codex/config-reference)。

同一输入和宿主的24小时完成结果复用，最多5个未完成任务，原生调用串行；原生10分钟超时、宿主领取15分钟过期。取消后不接受晚到报告；输入变化使结果失效；服务重启不自动重试被中断的付费会话。待领取任务保留，但服务重启不会自动派发这些旧任务。

## 实测用量与证据

规则采集仍为0模型调用，主动检查单独计量，未回报保持未知。首次 Codex 网页核验 Humanity 第三方仓库的宿主回报为输入87,295 tokens（其中缓存命中59,904）、输出1,775；这次检查并不满足极低 token 目标，用量不能直接当作账单。本轮进一步精简上下文与证据、提示最多4个关键来源，并支持复用当前聊天研究；尚无新的实测证明降幅。

证据：`evidence/agent-check-live-codex.json`、`agent-check-four-host-roundtrip.json`、`agent-check-adapter-update.json`；pi/DSH 实际 SDK 证据在 `adapters/evidence/pi-agent-check-session.json`、`dsh-agent-check-sdk.json`。四端传输测试中的报告是合成数据，只有上述 Codex 报告来自真实模型核验。

此前全工程100项通过，日志 `evidence/core-final-tests.log`；Headroom 106→7行，估算节省3,478 tokens。随后观察范围和目标时间补充后，19项服务回归通过，短日志压缩节省0。新增事实同步、风险隔离、幂等恢复、资料变化、配方限制、预算耗尽/跨日与当前宿主报告复用验证。16工具安装/SDK证据：`evidence/core-adapter-update.json`、`adapters/evidence/pi-core-session.json`、`adapters/evidence/dsh-core-sdk.json`。

## 每日预算与 Claude 诊断

2026-11-08调整：用户手动发起的检查和重试取消本地每日次数/token上限，失败只记录，不阻止后续手动检查。旧任务视为手动，历史用量不清零；未知用量仍标未知。后台自动检查才使用北京时间每日最多2次、120,000 tokens的准入预算，未知用量预留30,000，可在“档案与设置 → 后台自动检查预算”调整。当前后台采集仍为规则模式，不调用模型。模型账户自身的限制由服务商管理；详见 [预算范围](MANUAL_CHECK_USAGE.md)。

Claude 原始检查失败未回报用量；独立 bare 诊断返回403 / Insufficient account balance、API时长和usage为0，只代表诊断本身。正常/user settings 模式检测到 OAuth 登录，bare 模式丢失登录。已修正启动参数，但尚未验证成功生成；不能把 bare 错误推广为用户正常 OAuth 账户一定无余额。安全摘要：`evidence/claude-core-diagnostic.json`。

实时进度基线108项见 [LIVE_CHECK_PROGRESS.md](LIVE_CHECK_PROGRESS.md)；最新121项回归见 [策略与模型设置](TRIAL_POLICY_AND_MODELS.md)。
