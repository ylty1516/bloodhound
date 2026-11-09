# 受限执行后端

更新：2026-11-08。已经实现真实本地进程执行；不代表已有真实挖矿产出或原企划全部验收。

## 使用入口

进入 Web **运行中心 → 运行本机自检 → 开始本机自检**，约 12 秒可看到真实进程日志与结果，随时可停止。自检不连接项目网络、不启动矿工、不产生奖励。

真实项目从 **参与与运行 → 检查后的准备方案 → 查看准备方案 → 设置并启动试运行** 进入。已接入路线为 Opacra 测试网节点和单线程 CPU 挖矿；其他项目仍需专用配方。安全检查必须绑定候选、固定版本与发布包 SHA-256。网页检查、哈希匹配、表达参与意向均不能代替代码安全检查或本次运行授权。硬件适配评分仍只作建议。

启动前展示资源、网络、程序来源与范围。CPU 挖矿路线只收测试网公开地址，不收私钥或助记词。默认单次 60 秒、CPU 20%、内存 2048 MB、电脑空闲满两分钟后启动。用户开始使用电脑则停止，不会自行恢复；等待超过十分钟也结束。界面允许明确选择本次非空闲运行，不能由推荐意见静默修改。

## 生命周期与接口

`preview → queued → waiting_idle（可选）→ preparing → running → verifying → completed`。停止、超时、失败、用户活动、服务中断分别记为 cancelled / timed_out / failed / paused / interrupted。达到限时不伪装成任务成功。主库升级保留原有研究与观察记录。

- `POST /api/executions/preview`：driver、plan_id、options、inputs；生成十分钟有效的具体范围，不执行程序。
- `POST /api/executions/start`：quote_id、key、confirmed=true；检查资料与范围没有变化后执行一次。同一 quote 即使换 key 也不重复启动。
- `POST /api/executions/cancel`：id；停止整个进程组。
- `GET /api/executions`：阶段、状态、心跳、时长、已应用的限制、节点证据和回执状态。
- `GET /api/executions/logs?id=…&after=…`：增量游标，最多每次 200 行、每任务保留 600 行；程序输出保留上限 500 行，后续继续排空管道，避免阻塞。
- `GET /api/executions/receipt?id=…`：结束后的 JSON 回执，包含实际退出状态与是否验证成果；回执有 SHA-256。

所有接口沿用本机认证、Host 与 Origin 校验。API 不接受 shell、可执行路径或任意命令；只调用代码中固定的驱动。四宿主共用新增六个工具：prospect_executions、prospect_execution_preview/start/cancel/logs/receipt。工具总数 22；已安装桥接已更新，已运行宿主聊天需要重新加载工具列表。DeepSeek 完整宿主与 Claude 实际生成的既有未验收项仍保留。

SQLite 表 execution_quotes / execution_runs / execution_logs 持久化任务。运行目录位于私有 `%LOCALAPPDATA%/Prospect/executions/<id>`，不放保存库。服务重新启动只标记中断，不自动恢复矿工。并发上限一项。调度与执行不调用模型；不能把开发期模型用量算为零。

## 资源与边界

Windows Job Objects 施加 CPU 硬配额、进程组提交内存上限、最多八个进程、最后一个 Job 句柄关闭时结束整个进程树。可信 Python 启动器先等待 stdin，父服务成功分配 Job 后才允许启动项目；应用失败则不执行程序。依据：[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[CPU rate control](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information)。

运行窗口 5–900 秒，CPU 1–25%，内存 128–4096 MB。下载最多 128 MB、五分钟，ZIP 展开最多 512 MB，拒绝越界路径、符号链接与重复入口。仅解出 opacrad.exe 与 DLL，不执行钱包与批处理脚本。启动前重新核对程序哈希。工作目录总量在运行期间采样检查 1 GB，开始前保留至少 5 GB 空余；这些是容量检查，不是文件系统硬隔离。

Job Objects **不是安全沙箱**。项目进程仍在当前 Windows 用户权限下，独立 HOME 和环境变量白名单也不能阻止恶意程序读取账户文件。因此未经适用范围安全核验的项目不能启动。未实现 GPU、温度、网络流量硬配额、每日调度和断点自动继续。

## 项目路线与真实验证

Opacra 原官网发布包地址已失效，当前官网指向 [官方 v1.0.0 Release](https://github.com/opacra/opacra/releases/tag/v1.0.0)。下载仅允许固定 GitHub URL 与 release-assets.githubusercontent.com 重定向，再按固定 SHA-256 校验。实际下载的 21,768,985 字节 ZIP 校验通过，提取的 opacrad.exe 哈希见 `evidence/execution-artifact-final.json`。没有执行此程序；哈希通过不等于签名验证或代码审计通过。

驱动固定 --testnet，RPC/P2P 绑定 loopback，禁用 UPnP/ZMQ，不接收外来连接；仅有限出站同步。节点探针只读取 /get_info 并核对 testnet。高度与同步状态仅是节点证据；没有把它计为矿池接收份额、已挖区块或收益到账。实际节点、矿工运行及贡献/奖励验证仍待独立验收。

140 项完整 Python 回归通过，包含真实 Windows 子进程、子树取消、内存分配受限、超时、非零退出、服务进程被强制结束后的子进程清理、断线恢复、身份/范围变化拒绝、认证与产物校验。另有 4 项 JS 回归与语法检查。主服务 UI 实测两次自检：一次主动停止，一次正常完成，中文日志正确，回执下载成功。证据见 execution-tests-release.log、execution-resource-tests.log、execution-runtime.json 和 web-execution-result.png。

后续：针对一个当前开放目标完成固定版本安全审阅；形成用户可审阅的真实运行范围；取得该范围授权后做实际贡献探针验证。此后再实现每日调度、去重与预算、故障恢复，以及更多项目驱动。七天观察与原 P5/P6 验收保持独立，不以本机自检代替。
