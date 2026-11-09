# 环境审计与实现决策

核验日期：2026-11-06。唯一代码工作区为 `F:\Codex_Save_Library\05_Project_Folders\mining-radar\prospect-agent`。

## P0 审计结果

| 对象 | 已见事实 | 处理 |
| --- | --- | --- |
| 原 mining-radar | Python/SQLite 本地雷达，已有四条导入记录；自动来源主要为 X API；旧 app.py 约 315 行；19 项既有测试通过 | 只读读取 SQLite 并保留 legacy 标签；不导入有初始化副作用的旧模块 |
| 原服务与启动 | 有 launch.ps1 监督循环和 Windows Startup 中 MiningRadar.vbs；核验时旧 18765 端口未监听 | 不修改启动项、不强制开关旧服务 |
| Codex 既有巡检 | automation-4 为 Opacra 专项跟踪，核验时 PAUSED | 保留；不创建重复的大模型巡检 |
| mining-radar-site | 既有 Vinext/React/Cloudflare 项目；审计时 Git 工作区干净 | 保持原站点与部署，当前操作界面仅本机服务 |
| 旧 pearl-mining | 说明中的历史运行授权截至 2026-11-05 | 不继承为本次真实执行授权，不重启旧挖矿 |
| 本机 | i7-12700H、约 15.75 GB 内存、RTX 3060 Laptop 6 GB 显存，Windows 10.0.26200；工作区 F 盘本次约 174.35 GB 可用 | 数字随实时采样变化；功耗、温度未知，不推算保证收益 |
| 宿主 | Codex CLI 0.154.0、Claude Code 2.1.218、pi 1.4.0；DSH profile 存在，但指向的运行时缓存不可用 | 分别记录安装与验证范围；不以第三方 injector 版本代替 DSH 版本 |

原项目不能直接提供四宿主连接、来源证据模型、隔离运行状态和可审计模拟。选择在既有工程内创建独立模块，复用只读记录及已审计的业务需求，避免迁移原库和已有任务。旧数据不被新的来源结果覆盖。

## 技术与边界

- Python 3.12 标准库负责常驻服务、SQLite/WAL、规则采集及 CLI，降低首版运行依赖；Web 使用原生 HTML/CSS/JS，不新增构建链。
- 四宿主共用 `127.0.0.1:18766` 和同一用户级状态；OS 文件锁限制数据目录，TCP 绑定限制端口；会话退出不结束服务。
- hook 只唤醒服务，不塞入市场报告；按需工具传递摘要/分页。公开来源属于不可信数据，不作为安装、签名或付款指令。
- 发现与研究分开。GitHub 仓库只是线索；可靠上市或开放状态需要对应项目、交易所等一手证据。无法证明全网“尚未开盘”。
- 当前没有后台模型执行器，因此后台调用账本为零；预算耗尽后的付费模型行为尚未验收，不以零调用冒充这一能力。
- 用户推荐偏好记录为 `idle_only / do_not_disrupt`。真实资源调度尚未实现；没有将“偏好已记录”写成已经执行的 CPU/GPU 限制。
- 本机访问使用私有控制令牌或 SameSite/HttpOnly 浏览器会话，并检查 Host/Origin。信任当前 OS 用户；这不是面向公网或多租户的服务器。

## 回退与数据

停止新服务并在各宿主禁用/卸载 Prospect 即可回退；旧项目无需恢复或回迁。本地数据继续保留在 `%LOCALAPPDATA%\Prospect`。适配器卸载只处理所有权和哈希匹配的包；有用户改动时保留目录。不会删除宿主配置、其他插件或用户历史。

兼容审计详见 `adapters/HOST_AUDIT.md`，安装记录见 `evidence/host-installation.json`；实际项目调查见 `FIRST_PROJECT_RESEARCH.md`。官方接口与来源引用均保留在对应文档，不能用本审计替代未来版本回归。
