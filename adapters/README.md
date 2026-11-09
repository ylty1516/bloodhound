# Prospect 宿主适配器

本目录实现四端薄适配和 Python 标准库 MCP stdio 桥。当前工具只访问状态、公开来源、评估、研究记录与模拟；没有真实挖矿、安装项目、签名或付款工具。模块导入、MCP 握手和工具发现不启动模型。

## 状态与证据

- 已执行 `python -m unittest discover -s tests -p test_adapters.py -v`：当前 15 项通过，包含隔离固定版本 DSH SDK 的真实 schema 加载、工具执行和卸载回归。最新日志在 `evidence/adapter-tests-dsh-sdk.log`；先前 12/14 项日志保留。未安装可选 SDK 测试依赖的环境会明确跳过该项，不会伪报实测。
- 测试覆盖 MCP initialize / tools/list / tools/call 的真实 stdio 子进程往返、CLI 失败的 `isError: true`、错误参数拒绝、四端生成、改动文件保留、配置备份与 Windows 特殊字符路径。
- CLI 代理测试使用临时假 CLI，未在这些测试中接入真实宿主或实际服务。JavaScript 检查仅验证语法，没有把它当作 DSH 运行时验收。
- Codex、Claude、pi 当前包位于 `prepared-v2/`；DSH 修复包为 `prepared-v3/deepseek`。支持候选分页 `offset >= 0`、`1 <= limit <= 50`。旧包保留历史证据，其中旧 DSH 包已有真实 SDK 加载失败记录，不应继续使用。主 agent 已正式安装启用三个可用宿主；DSH 仅安装隔离 SDK 测试依赖，没有全局宿主安装启用。
- 在工作区隔离目录执行了 `install` → `backup` → `uninstall` 命令，均成功；留下的 `evidence/lifecycle-backup` 仅含非敏感生成配置。
- Claude 本机 `plugin validate` 已通过，仅提示缺少 author 元信息。最初 pi loader 验证记录在 `evidence/host-validation.json`；后续 `evidence/pi-session-check.mjs` 使用真实已安装 SDK 创建内存会话并调用 `bindExtensions`，触发一次 session_start、ensure 成功，再由原生 wrapped 工具调用真实 status。0 prompt、0消息、0模型/provider/fetch调用，结果见 `evidence/pi-session-result.json`。未把它当作交互 CLI 或模型工具拦截验证。
- `marketplaces/codex` 与 `marketplaces/claude` 已创建。Claude 原生 validate 接受 marketplace 和插件；Codex 0.154.0 通过临时 `-c` 覆盖的原生 plugin list 识别到 Prospect，未改全局配置。详见 `evidence/catalog-validation.json` 和 `ACTIVATION.md`。
- `evidence/mcp-live-check.py` 已在允许本地套接字访问的执行环境连接真实 18766 服务，initialize、tools/list（7 个）及 prospect_status 均成功；未请求模型、扫描或宿主会话。结果在 `evidence/mcp-live-result.json`。默认沙箱此前以 WinError 10013 拒绝本地套接字，该次失败未被当作产品成功。
- 用户报告已完成 Codex `/hooks` 首次信任，随后原生 app-server `hooks/list` 独立确认已安装插件 enabled + trusted。`evidence/codex-session-check.py` 还执行了不发送 turn/start 的 ephemeral 临时会话探针；返回 path:null、0 turns，但未观察到 hook 执行通知，`verified_hook_completed:false`。真实启动/恢复执行验收仍开放；没有修改受信任 hook 的内容。
- DSH 的真实 Cordis Context、官方 ToolRegistry 和 Prospect 插件已完成无模型集成：7 工具注册、ensure、真实 status/候选分页、错误参数拒绝、dispose 后注销及再次调用失败。见 `evidence/dsh-sdk-result.json`。固定 SDK 版本和安装完整性记录在 `evidence/dsh-sdk-installation.json`，复现方法见 `.dsh-sdk-qa/README.md`。这不代表完整 DSH CLI/Web、profile bundle loader 或恢复路径通过。
- Headroom 轻量日志压缩已运行；最新 15 项测试短日志为 21→21 行，估算节省 0 token，见 `evidence/headroom-dsh-sdk-stats.json`。先前日志、压缩结果和 stats 均保留，不声称有节省。
- 本机审计及官方来源见 `HOST_AUDIT.md`。pi 与 DSH 的 SDK 生命周期和工具已实测；Codex/Claude 的真实 hook 执行、交互恢复、多会话与 DSH 完整宿主仍有未完成项，不能写作四端实连全部通过。

## 结构与启动

`bridge.py` 通过逐行 JSON-RPC 2.0 提供七个 MCP 工具，所有动作转给配置指定 checkout 的 `python -m prospect tool NAME JSON`。无 shell 拼接工具参数。错误保留为错误结果，stdout 仅输出协议消息。

`launch.py ensure` 只调用 CLI ensure，成功时不输出上下文。生成的 Windows hook 使用 PowerShell 直接命令的 UTF-16 编码参数，保证多层 shell 与中文路径不破坏参数；完全相同的可读源码保留在 `session-start.ps1`，没有设置 ExecutionPolicy Bypass。包的 hook 配置和源码必须一起审阅。MCP 直接传递 command/args，不经过 shell。

`manage.py` 从实际运行它的 `sys.executable` 获取 Python，也接受显式 `--python`、`--project-root`、`--data-dir`、`--port`。包内路径在生成时确定；移动包或更换解释器后应生成到新目录，不手改所有权哈希。

## 安装、备份与卸载接口

以下包装工具接口已在工作区隔离目录验证；主 agent 也已将 pi 安装到真实宿主扩展目录。以下是接口形状，具体执行记录见 `ACTIVATION.md`：

```text
python -m adapters.manage install --host HOST --destination ABSOLUTE_NEW_DIRECTORY
python -m adapters.manage backup --destination INSTALLED_DIRECTORY --output NEW_BACKUP_DIRECTORY
python -m adapters.manage uninstall --destination INSTALLED_DIRECTORY
```

`install` 仅在指定的新目录创建带所有权记录的包，绝不覆盖已有目录，也不修改宿主注册、信任、配置或软件版本。`backup` 只复制本工具生成且哈希未改动的非敏感配置；不会读取或备份整个宿主配置文件。`uninstall` 先核对位置、文件集、目录集及全部哈希，发现任何用户改动就保留整个目录。先通过宿主界面撤销注册，再卸载包；本工具不会结束共享服务。

Codex 和 Claude 包各含原生 manifest、`hooks/hooks.json` 与 `.mcp.json`，现已通过主 agent 安装启用。pi 已位于其全局 extensions 下的 owned 子目录；注册只使用 `session_start` 和七个原生工具。不要同时在同一宿主注册原生工具和重复 MCP 工具。

DSH 包使用 `dsh.bundle`、`cordis.patch.yml`、`apply(ctx)`、`inject = ['tools']` 与 `ctx.effect` 清理资源。其参数转换适配 DSH 的严格 schema 子集，原始数值与非空限制继续由 Python 桥校验。`COMPATIBILITY.json` 的 `runtime_unverified` 指完整宿主仍未验证；已完成的隔离 SDK 验证见上述独立证据。须确认实际 DSH 宿主版本及其 peer 解析，再使用目标版本的官方安装入口；不得将现存失联缓存目录当作可用运行时。

会话释放不停止共享 Prospect 服务。用户级锁、API 鉴权、业务幂等与后台任务寿命由核心 CLI/服务负责。适配器成功退出不能证明某项项目任务已完成。
