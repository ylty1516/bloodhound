# 从研究报告到参与准备

2026-11-07更新：尝试建议采用安全优先策略，硬件不再筛除推荐；模型可在独立页面配置。以 [最新策略与模型说明](TRIAL_POLICY_AND_MODELS.md) 为准，下文旧的全条件筛选描述保留为历史实现背景。实际执行条件仍独立检查。

2026-11-06。入口为“参与与运行 → 检查后的准备方案”。每份完成报告形成一份可追溯方案；符合参与请求条件的项目另外进入提请参与列表。资料不足与风险不通过保持可见，不冒充可运行机会。

## 事实衔接

Agent 报告包含七个核验主题和公开来源。新 schema 使用可为空的 `project_facts`，有事实时必须声明项目身份一致、官方 URL，以及白名单字段的 value / sources / kind / scope / note。字段包括市场阶段、资源要求、参与窗口、奖励单位。引用必须在报告中出现，数值受范围限制；否定现货结论必须限定范围，unknown 不覆盖已有事实。

身份一致且证据校验通过时，在报告完成事务中写入候选事实并解决对应修订的研究任务；重新计算适配和提请资格。身份冲突只保存报告；矛盾证据保留为待核验。风险不通过的报告不得触发参与请求。协议校验不能代替对资料真实性的研究。

已在当前聊天核验过的来源可通过 `prospect_research_resolve` 复用，result 包含 `candidate`、`report`、`host`。这也生成方案，来源明确标为宿主已提交的研究；不再次启动 CLI。当前聊天/开发用量不伪称为零，也不伪装成新增产品检查会话。仅适配器 Bearer 凭据允许提交证据，网页不能冒充宿主。

## 配方与模拟

配方在 `recipes/*.json`，以版本、精确候选 URL 与 identity_key 绑定网络；测试网不能自动切换到主网。必须记录下载来源、发布哈希、是否在本机验证、外部限制和交付定义。允许步骤为 preflight / prepare / run / verify / deliver；不接受 shell 命令字段。

准备方案检查资料新鲜度、七项核验、设备/个人条件、市场资格、配方与包验证，状态为 needs_information / not_recommended / ready_for_simulation。所有准备方案 execution_authorized=false。支持的 Opacra 路线另有 execution_drivers 和 live_execution_implemented=true；真实启动使用单独的运行范围授权，见 EXECUTION_BACKEND.md。

模拟记录在 SQLite 持久化。相同计划与幂等键复用结果；失败后可按检查点恢复；候选、设备或配方变化时拒绝旧恢复请求。失败步骤、已完成步骤及 mock 标记完整保留。此模拟取消只处理失败预演状态；真实进程使用 /api/executions/cancel。

新增工具：`prospect_plans` 查询方案，`prospect_plan_simulate` 执行无外部副作用的模拟，`prospect_monitoring` 控制规则持续发现。加入进度与六个执行接口后，四端总计22工具。

## 首个真实准备目标

Opacra testnet 3：官网 https://opacra.org/ 与其链接的 https://github.com/opacra/opacra 双向核对；网页和公开校验和文件中的 Windows 1.0.0 包哈希一致。网页声明主网尚未启动、测试币不转主网币；这些是项目方自述，不代表独立审计或安全保证。

- 配方：`recipes/opacra-testnet-1.0.0.json`，精确绑定 `opacra:testnet3`。
- 证据：`evidence/opacra-official-page.html`、`opacra-published-checksums.asc`、`opacra-host-review.json`。
- 发布包已从官方 GitHub Release 下载并通过本机 SHA-256 校验；仍未执行二进制、验证签名或完成代码安全审计，未产生挖矿贡献。
- 官网称主网计划在 2026-11-08 14:00 UTC 上线；这是未来计划，不能作为主网已开放证据，临近时需要重新核验。测试网路线不会自动升级为主网运行。
- 完整通过的 UI 模拟使用隔离合成项目；不把它写成 Opacra 成功运行或获得奖励。

受限运行器、下载校验、停止、服务中断恢复标记与节点信息探针现已实现。下一步完成目标版本安全核验，形成具体授权范围，再进行真实项目验收；七日观察与原P5/P6验收不由本机自检替代。
