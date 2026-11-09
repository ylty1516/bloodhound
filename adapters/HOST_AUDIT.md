# 四宿主只读审计

核验日期：2026-11-06，Asia/Shanghai。初审覆盖本机命令、非敏感配置结构、已安装 pi 文档和官方网页；随后主 agent 完成三个可用宿主的正式安装。本目录补充了无 prompt 的 pi 内存 SDK 会话及 Codex 原生临时会话验证，没有请求模型生成、读取凭据内容或安装 DSH 运行时。

| 宿主 | 本机证据 | 当前加载状态 | 适配路径 |
| --- | --- | --- | --- |
| Codex | CLI `0.154.0`；原生 app-server `hooks/list` 读取已安装插件，`enabled:true`、`trustStatus:trusted` | 主端安装 `prospect@prospect-local-codex`；用户报告已完成首次信任，随后只读 RPC 独立证实信任；临时 thread/start 没观察到 hook 执行通知 | 原生插件 hooks/hooks.json + .mcp.json；真实 SessionStart 执行仍待实测，桌面版本未单独核定 |
| Claude Code | `2.1.218`；官方 plugin validate 接受生成包，仅缺 author 警告 | 主端已正式安装并启用 `prospect@prospect-local-claude`；真实新会话和恢复 hook 执行未测 | 插件 SessionStart command + MCP；注册与验证不能代替运行证据 |
| pi | `1.4.0`；实际 SDK `createAgentSession`、`bindExtensions` 和原生 wrapped 工具执行 | 主端安装到 `~/.pi/agent/extensions/prospect`；真实 SDK session_start=1、ensure 成功、status 成功；0 prompt、0消息、0模型调用 | 原生扩展自动发现/显式路径；SDK 已验证，交互 CLI 自动发现及恢复仍待测 |
| DeepSeek Harness | 原全局 dsh 运行时不可确认；后续在项目隔离目录安装官方 Cordis 4.1.0、dsh-tools 0.0.1-rc.1 与锁定依赖，真实 SDK 集成通过 | 完整宿主仍 `runtime_unverified`；SDK 注册7工具、ensure、status/分页、参数错误与dispose已验证；未改全局profile、未注册LLM或账户 | 当前修复包为 prepared-v3/deepseek；SDK通过不替代真实宿主安装/启动/恢复验收 |

Codex 命令入口：`C:\Users\yyx\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe`。它报告的是 CLI 版本，不能代替桌面应用版本。运行只读 version/help 时曾报告无法清理沙箱外 arg0 临时目录；命令仍给出版本和帮助结果。没有使用 hook trust 绕过开关。

Claude 用户配置位于 `C:\Users\yyx\.claude`；pi 用户配置位于 `C:\Users\yyx\.pi\agent`。这里只提取键名和扩展状态，没有输出 env 内容。DSH profile 引用的本地 `@dsh-external/dsh-super-injector` 版本为 `0.3.3`，这是第三方插件版本，绝不能写成 Harness 版本。

Python 实测 `python --version` 为 3.12.10。`py -3.12` 在本次沙箱报告 No installed Python found，因此包装器默认使用已启动解释器的绝对路径，不依赖 py launcher 注册表。

补充检查了用户/公共桌面、用户/公共 Start Menu 的相关快捷方式、Local Programs、Local AppData、Program Files、ProgramData、常见卸载注册表及可见进程。未发现其他 DSH 桌面入口。这是本次执行环境可见范围的结果，没有对全盘未知位置作否定结论。

Codex 0.154.0 的 plugin 帮助列出 add/list/marketplace/remove，没有本地 validate 子命令。首次信任由用户在 CLI `/hooks`，或桌面 `Review hooks` / `Settings > Hooks` 完成；用户回复“好了”是用户报告，不是运行日志。之后 `evidence/codex-hook-discovery.json` 独立确认当前安装定义已信任；本探针没有写信任或修改 hook。`evidence/codex-session-result.json` 记录独立 app-server `thread/start` 的 `ephemeral:true`、`path:null`、0 turns，但 12 秒内没有 hook/started 或 hook/completed，所以 `verified_hook_completed:false`，不能把临时线程创建成功写成 hook 执行通过。

pi 的 `evidence/pi-session-result.json` 来自真实 SDK 内存会话和 ExtensionRunner，明确没有读取用户凭据、没有调用 prompt 或模型。原生工具 wrapper 返回真实服务状态；该路径未测试 agent-loop 的 tool_call/tool_result 拦截。单次事件分发约 15.6 ms、ensure 子进程约 706 ms，不能当作 p95 或长期性能结论。

DSH 隔离 SDK 证据见 `evidence/dsh-sdk-result.json`：使用官方 Cordis Context 与 SystemPrompt/ToolRegistry 服务真实挂载 Prospect，状态读取返回当时主服务 PID 32584；候选分页取到1/34条，limit=0返回错误，dispose 后7工具全部移除。没有挂载 LLM/agent loop 或使用全局 profile，JavaScript fetch 尝试为0。原包的 required:false、数值限制关键词和 object 参数不符合发布版 schema，已修复生成器并保留 `dsh-sdk-v2-result.json` 失败证据。SDK直接版本和所有解析依赖锁定于 `.dsh-sdk-qa/package-lock.json`；这些测试不是完整 DSH 宿主运行证据。

## 官方接口核验

- [OpenAI 插件打包](https://developers.openai.com/plugins/build/plugins)：手动安装的桌面插件可包含生命周期 hook，默认发现 hooks/hooks.json，支持兼容 manifest。
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)：SessionStart 覆盖 startup/resume 等会话来源；非托管 hook 需要审阅当前定义；插件 hook 与配置层共同加载。模型上下文不应塞入周期采集数据。
- [Claude hooks](https://code.claude.com/docs/en/hooks)：SessionStart 可调用 command hook；长期任务应有独立生命周期。当前网页特性不自动证明本机 2.1.218 的所有新字段可用，因此包仅使用基础字段。
- [pi 扩展](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)：全局扩展目录、session_start、原生工具与 MCP；本机 1.4.0 随包文档也确认相应接口。
- [DSH 生命周期](https://deepseek-harness.github.io/deepseek-harness/en/develop/framework/)：[打包与安装](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/publish)、[工具定义](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/tool)说明 apply、服务注入、effect 清理、bundle patch 与 defineTool。尚缺目标运行时实测。
- [DeepSeek 官方 Harness 入口](https://www.deepseek.com/harness/)直接链接 `deepseek-ai/deepseek-harness` 仓库和上述开发文档；身份关系与当前 bundle 格式复核在 `evidence/dsh-source-review.json`。包结构符合所读文档，不代表未知目标版本可以实际加载。
- [Codex app-server](https://learn.chatgpt.com/docs/app-server)区分 thread/start 与 turn/start；本探针仅创建 ephemeral 会话，没有调用生成入口。

## 后续需要的真实证据

对每个宿主分别记录安装位置、版本、注册与信任状态、实际首次启动/恢复连接日志、模型调用增量、额外启动延迟和多实例结果。当前包装测试与假 CLI 测试不填写这些验收项。DSH 若缺可用客户端可继续交付待验证包，但不能通过 P1 的四端实连条件。
