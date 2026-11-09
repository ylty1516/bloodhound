# 宿主安装记录与剩余验证

主 agent 已于 2026-11-06 正式执行下列 Codex、Claude 与 pi 安装命令，均退出 0；安装状态摘要在工程根目录 `evidence/host-installation.json`。这些是已执行记录，不应在现有目录重复安装。安装、信任和实际生命周期执行分别验收。命令执行目录：

`F:\Codex_Save_Library\05_Project_Folders\mining-radar\prospect-agent`

## Codex

本地市场遵循[官方 marketplace 格式](https://developers.openai.com/plugins/build/plugins)，根目录有 `.agents/plugins/marketplace.json`，插件 source.path 相对市场根目录。已通过当前 CLI 的原生列表解析检查，完整调用参数记录于 `evidence/catalog-validation.json`；检查只用了临时 `-c` 参数。

```powershell
codex plugin marketplace add 'F:\Codex_Save_Library\05_Project_Folders\mining-radar\prospect-agent\adapters\marketplaces\codex' --json
codex plugin add prospect@prospect-local-codex --json
```

安装结果为 `prospect@prospect-local-codex`，版本 `0.1.0`，已启用。用户通过 [hook 审阅入口](https://learn.chatgpt.com/docs/hooks)完成操作并回复“好了”；这是 `user_reported_complete`。后续原生 app-server `hooks/list` 独立确认 enabled + trusted，证据在 `evidence/codex-hook-discovery.json`。未自动写信任记录，未使用 `--dangerously-bypass-hook-trust`。

实际运行验证仍未通过：`evidence/codex-session-check.py` 在独立 app-server 创建 `ephemeral:true` 的临时会话，确认 `path:null`、0 turns，没有发送 `turn/start`；12 秒内没有收到 hook/started 或 hook/completed，记录见 `evidence/codex-session-result.json`。因此不能把注册、信任或 thread/start 成功当作 SessionStart 执行证据。后续应在真实新会话和恢复会话分别观察执行，保持当前受信任 hook 文件不变。

## Claude Code

市场遵循[官方 marketplace 格式](https://code.claude.com/docs/en/plugin-marketplaces)，包含 `.claude-plugin/marketplace.json`、owner 和相对插件 source。当前 2.1.218 的官方 validator 已接受市场及插件；插件仅有 author 元信息警告。

```powershell
claude plugin marketplace add 'F:\Codex_Save_Library\05_Project_Folders\mining-radar\prospect-agent\adapters\marketplaces\claude' --scope user
claude plugin install prospect@prospect-local-claude --scope user
```

本机 2.1.218 接受上述 `--scope user`，marketplace add 返回 Successfully added，plugin install 返回 success(user)。已安装启用 `prospect@prospect-local-claude`，版本 `0.1.0`；实际新会话和恢复的 SessionStart 尚未验证。不得把安装列表当作 hook 执行证据，也不应修改已有 permissions 或 env 来消除提示。

## pi

当前 1.4.0 的实际扩展 loader 已接受该扩展，注册 session_start 与七个工具。主 agent 已执行下面命令，创建 owned 子目录；重新执行会因目录已存在而拒绝覆盖。

```powershell
python -m adapters.manage install --host pi --destination 'C:\Users\yyx\.pi\agent\extensions\prospect'
```

`evidence/pi-session-check.mjs` 已使用安装目录中的扩展和本机真实 SDK 创建内存会话，调用 `AgentSession.bindExtensions()` 触发一次 session_start，ensure 成功；从该会话注册表中的原生 wrapped 工具调用 prospect_status 成功。没有 prompt、消息或模型调用，未使用用户凭据。该证据覆盖 SDK 生命周期与工具，不覆盖交互 CLI 自动发现、恢复和 agent-loop 工具拦截；见 `evidence/pi-session-result.json`。

全局 extensions 目录的自动发现与交互 reload 路径仍需单独实测。本扩展原生注册工具，不重复注册同名 MCP 服务。如需备份/卸载，只使用包装工具的对应 owned 目录操作。

## DSH 与包装绑定

当前 DSH 修复包为 `prepared-v3/deepseek`；旧 `prepared-v2/deepseek` 已被真实 SDK 验证发现 schema 不兼容，不能继续当作可用候选包。官方固定 SDK 已在 `.dsh-sdk-qa` 隔离安装，全部安装脚本禁用，未覆盖 `.dsh` profile、注册账户或安装桌面应用。真实 SDK 加载、7工具、ensure、只读状态与候选分页、错误参数和 dispose 清理通过，见 `evidence/dsh-sdk-result.json`。

这仍不是完整 DSH 宿主安装启用：CLI/Web、profile bundle loader、启动与恢复未验证。官方身份与 bundle 格式证据在 `evidence/dsh-source-review.json`；隔离测试复现入口在 `.dsh-sdk-qa/README.md`。以后须先确认真实客户端与版本，再选择其官方 bundle 安装入口。

本版是绑定本地 checkout 的适配器：Python 路径在生成时检测，产品代码由 runtime.json 中的 project_root 指定。marketplace 内的 hook 与 MCP 配置引用该市场中的已审阅脚本路径。保留市场和工程目录，搬迁时重新生成并通过宿主更新；不要把复制缓存等同于独立可移植发行包。
