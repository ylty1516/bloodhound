# DeepSeek API 接入

2026-11-08。Agent 与模型页增加独立 DeepSeek API 配置，并接通项目检查。它与 DeepSeek Harness 宿主适配器是两个入口。

## 使用

1. 打开 http://127.0.0.1:18766/#agents，在 DeepSeek API 区填写接口地址和 API Key。默认官方地址为 `https://api.deepseek.com`；兼容服务可填自己的 HTTPS Base URL（支持端口和路径）。不要填写完整 `/chat/completions` 路径，也不要在 URL 中放密钥。
2. 选择或填写模型 ID，设置思考强度与单次输出上限，勾选启用，保存接口设置。默认模型 `deepseek-flash`、思考 `high`、输出上限12000；可以选择 `deepseek-v4-pro` 或接口实际支持的其他模型。
3. 点击“测试连接并读取模型”。只请求 GET `/models`，不发起文本生成。模型列表连通不代表额度充足或所有参数均可用于生成。
4. “开始参与”默认自动识别当前宿主。需要用 API 检查时，在该页展开“其他检查方式”，临时改用 DeepSeek API。保存配置本身不会启动检查。
5. 新检查显示阶段、心跳、请求模型与强度、接口实际回报的型号、最终报告和接口返回的 token 用量。取消后不采用迟到结果；已经发出的请求可能仍产生服务方费用。

思考选项为关闭、low、high、max；开启时发送 `thinking.type=enabled` 和 `reasoning_effort`，关闭时发送 `thinking.type=disabled`。以2026-11-08读取的[官方接口说明](https://api-docs.deepseek.com/)及[思考模式说明](https://api-docs.deepseek.com/guides/thinking_mode/)为依据。不同兼容网关的参数支持仍需实际验证。

## 凭据与配置

密钥由当前 Windows 用户的 DPAPI 加密，保存在 `%LOCALAPPDATA%\Prospect\credentials`。数据库只保存随机凭据引用和非秘密配置。页面不会回传密钥；输入留空保留原密钥；“移除已保存密钥”同时停用接口。改变接口地址时需要重新输入目标地址的密钥，防止旧密钥被无意转发。API重定向不被跟随，错误响应体不写入用户报告。

接口保存与测试沿用本机控制凭据、浏览器会话和 Origin 检查。非回环 HTTP 地址被拒绝。当前加密保存实现仅支持 Windows，尚未扩展 macOS/Linux 密钥库。

每次任务冻结配置。队列等待期间修改接口配置时，旧任务停止并要求重新发起；不会悄悄切换模型或凭据。手动发起API检查没有本地每日次数/token上限，保留报告复用、取消和实际用量记录；后台自动检查才使用准入预算及未知用量预留。服务商账户的额度、限速和单次输出参数仍由接口执行。思考内容不存储、不展示，只有任务阶段与最终报告进入记录。

## 能力范围与验收

此入口使用本机只读抓取的有限公开证据包（最多3个URL，每页最多128KB读取、保留约10000字符文本），不是完整工具调用 Agent。请求会发送项目上下文、精简设备和偏好及证据包；页面已明确提示。模型不能自主搜索或读取整个仓库，只允许引用包内来源。有限证据包不能完成固定版本源码审计，模型返回 source_review/pass 时强制保持待核验，不能据此启动项目软件。原生 Codex / Claude 与四宿主工具通道仍保留其现有能力。

已验证：模拟API真实HTTP流、Windows加密保存/移除、拒绝重定向与密钥回显、参数传递、取消、截断与错误引用、配置冻结、用量统计、API鉴权及页面交互。完整153项Python回归通过；浏览器在独立5713端口验证保存、连接模型列表、刷新保留、地址变更保护、移除密钥和默认Agent保存。主服务已更新，DeepSeek保持未启用、未配置真实密钥。

证据：`evidence/deepseek-release-tests.log`、`deepseek-provider-tests-final.log`、`deepseek-service-tests.log`、`deepseek-runtime.json`、`deepseek-ui-qa.json`、`web-deepseek-api.png`。未使用真实 DeepSeek 账户调用，尚未验证真实账户额度、兼容网关或真实模型报告质量。
