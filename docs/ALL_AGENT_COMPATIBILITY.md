# 四端检查的共同防护

2026-11-09。覆盖 Codex、Claude Code、pi、DeepSeek Harness，以及独立的 DeepSeek API。目的是提前发现不兼容、保留已完成的工作并给出可修正反馈；不能保证宿主登录、网络和模型服务始终可用。

同日新增全量目录：当前最新生成包为prepared-v13、仍29工具，prospect_candidates支持全量线索和筛选，prospect_assess可读旧存档。五处桥接已更新，四端实际CLI/HTTP传输验证见evidence/lead-catalogue-four-adapters.json；下文原native/SDK验收范围不因此提升。来源恢复见[DISCOVERY_SOURCES.md](DISCOVERY_SOURCES.md)。

| 入口 | 启动前核对 | 报告提交与恢复 |
| --- | --- | --- |
| Codex CLI | 比较桌面随附、独立安装与 PATH 的实际版本；本机 help 核对必要参数 | 原生结构化约束；未采纳报告留私有目录，保留已知用量 |
| Claude Code CLI | 比较独立安装与 PATH 的实际版本；核对 JSON schema、工具白名单、MCP 隔离等参数；不支持所选 effort 时在生成前返回原因 | 提取用量后再校验 structured_output；格式失败不丢失已知用量或报告 |
| 四端宿主会话工具 | 领取时返回同一个 report_schema 与稳定 report_schema_id；pi / Harness 不假设存在可独立唤起的 CLI | validate → 修正 → complete；同一租约内补交，不重新检索、不自动换模型 |
| DeepSeek API | 最近一小时、相同接口与凭据引用的模型目录若明确缺少所选型号，在生成前停止；旧目录或未知目录不冒充可用性证明 | 截断、JSON 或引用错误仍保留服务端已回报的用量与正文；不保留 reasoning_content |

版本和参数只做本机 `--version` / `--help` 读取，缓存五分钟；普通网页轮询不反复执行版本探测。CLI、权限、联网和模型可用性是不同条件，安装了客户端并不等于登录或模型调用成功。

## 同一任务修正报告

1. 调用 `prospect_check_claim`，保存返回的 id、host、lease_token、report_schema 和 report_schema_id。令牌只在工具调用中使用。
2. 用宿主实际提供的只读检索能力核验，真实阶段变化时调用 `prospect_check_progress`。
3. 用 `prospect_check_validate` 校验报告；也可直接 complete，后端会自动执行相同校验。
4. 返回 needs_correction 时，任务仍为 running，网页显示“报告已收到，等待 Agent 修正格式”。根据 issue 和领取时的 schema 修正后，使用原 id、host、lease_token 补交。不将这次格式问题解释成项目不值得参与。
5. valid 仅表示格式通过，仍需 complete 才保存事实。完成后删除临时未采纳报告；失败报告保存在私有运行目录 `agent-check-work/<id>/report.json`，不会作为已核实事实公开。

取消、租约过期、宿主不符及资料变化仍拒绝提交；补交不会绕过这些边界。只有本机受信任的适配器能校验和提交，网页 Cookie 不具备此权限。已知用量在修正期间就计入统计，完成后不会重复计算；宿主未回报的用量和实际模型仍显示未知。schema 校验不证明来源真实，也不授予挖矿或资金操作权限。

## 实际验证与限制

- 本机 Codex 0.167.0-alpha.3.2、Claude Code 2.1.218 的版本与必要 help 参数已实读核对，见 `evidence/all-agent-capability-preflight.json`。此步骤没有调用模型。
- 四端同租约修正、HTTP 权限和桥接传输使用明确标注的合成报告验证，不能替代真实模型研究。
- pi 1.4.0 的真实 AgentSession 和固定版本 Cordis/DSH 工具注册服务均实测加载29工具，并调用正式服务的状态及检查队列；零模型调用。证据见 `adapters/evidence/pi-all-agent-compatibility-session.json` 与 `dsh-all-agent-compatibility-sdk.json`，不等同于交互CLI或完整Harness运行。
- Codex 上一轮真实 SHEAR 报告已完成；本轮没有再次启动模型研究。Claude 成功生成、pi 原生交互生成与完整 DeepSeek Harness 运行仍待各自实机验收。
- 五处已安装/marketplace 桥接与四端 prepared-v12 包共 29 工具。运行中的宿主可能需要重新加载工具列表；旧 complete 工具也会得到后端的 needs_correction 反馈。更新不修改 Hook、首次信任、模型偏好或认证。

验证命令、结果和服务状态以 [STATUS.md](../STATUS.md) 最新记录为准。
