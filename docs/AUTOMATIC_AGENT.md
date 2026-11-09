# 自动识别检查 Agent

2026-11-08。开始参与页的“交给谁检查”改为只读的“检查 Agent · 自动识别”。正常操作只选项目；临时手选宿主或 DeepSeek API 收入默认折叠的“其他检查方式”。旧浏览器会话迁移时保留项目，默认进入自动识别。

## 识别依据

四宿主生成适配器的 runtime.json 均声明自己的 host。启动 hook、MCP 连接、pi session_start 和 DeepSeek Harness apply 的既有 ensure 路径会携带声明。工具调用也会报到。CLI 沿本次调用的真实父进程链寻找宿主；Node/Bun 宿主须有适配器声明，不根据一个普通 Node 进程猜测。旧 Codex MCP 无 host 参数时仍可由实际 codex.exe 祖先进程识别。

只读进程名称、父 PID 和创建标记，不读取命令参数、聊天、认证文件或全量环境。服务验证创建标记，将少量观察保存在私有数据库。网页公共状态不包含 PID 或创建标记；登记接口要求原生控制凭据，浏览器 Cookie 不能登记宿主。后台项目检查带内部标记，不能变成用户当前宿主。

选择最近启动/调用 Prospect、且来源进程仍存活的 Agent；退出或 PID 被复用即不再采用该观察。多个宿主同一时间报到且无法区分先后时显示等待确认；没有观察时显示“等待 Agent 连接”。安装了 CLI、模型偏好、服务最初继承的环境均不证明当前宿主。这里识别最近与 Prospect 交互的宿主，不读取系统前台窗口，因此多个 Agent 同时打开时会跟随最近的实际交互。

## 调度

自动模式发送 `host=current`，由服务器在发起时解析，避免页面陈旧或保存的默认值覆盖当前宿主。解析失败时不派发模型、不扣检查次数；可以连接宿主后重新检测，或手动展开备用入口。发起后冻结宿主，切换 Agent 只影响后续任务。Codex/Claude 使用已有本机 CLI 检查通道，pi/DeepSeek Harness 沿用已连接宿主领取协议；自动识别不等于四端均能自动执行模型请求。

模型和思考强度仍使用该通道已保存的设置，不能从进程名称推断当前聊天实际型号。DeepSeek API 是独立接口，不被当成 DeepSeek Harness 宿主；需要时在“其他检查方式”手动选择。

## 验证与范围

- 完整164项Python回归通过，含10项识别测试和原生鉴权/自动派发路由。覆盖真实父链与其他运行进程区分、四种宿主声明、普通Node不猜测、内部后台检查排除、退出/PID复用、最近交互、同时报到、重启保留、无观察不回退默认值。`evidence/agent-context-full-tests.log`。
- 22项参与状态/宿主选择断言与4项既有交互回归通过。隔离5715服务浏览器验证：保存默认API但自动识别Codex；请求实际绑定Codex；模拟切换Claude时既有排队任务保持Codex，停止后自动显示Claude；无观察时停止自动派发；手选API入口仍可用。此验证不调用模型。
- 正式服务经当前聊天实际 Prospect MCP 工具调用确认 `host=codex, source=tool`，并在页面显示“已识别 · Codex”。没有为验证发起真实项目检查或挖矿。手机390×844检查文档/滚动宽度均376px。
- prepared-v8含四宿主包；5份现有Codex/Claude/pi和marketplace包只更新bridge.py、runtime.json及所有权哈希，先校验、私有备份；hook命令及宿主设置未修改。DeepSeek完整宿主运行、其他操作系统与四端切换的真实联合验收仍未完成。

证据：`agent-context-runtime.json`、`agent-context-adapter-update.json`、`agent-context-ui-qa.json`、`agent-context-ui.png`、`agent-context-mobile.png`（均在 evidence/）。主服务停止方式仍为 `python -m prospect stop`。
