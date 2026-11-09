# 本机运行与接续

工作目录：`F:\Codex_Save_Library\05_Project_Folders\mining-radar\prospect-agent`。Python 3.12.10；服务无第三方 Python 运行依赖。

## 已执行的入口

| 操作 | 在工程根目录执行 | 结果与证据 |
| --- | --- | --- |
| 启动/复用服务 | `python -m prospect ensure` | 本机 18766；并发和崩溃恢复见 evidence/runtime-lifecycle.json |
| 紧凑状态 | `python -m prospect tool prospect_status '{}'` | 服务、候选数量、后台用量与观察状态 |
| 公开来源扫描 | `python -m prospect scan` | GitHub 公开真实数据，限流与冷却生效；保留扫描账本 |
| 硬件 | `python -m prospect hardware` | 实际 CIM/NVIDIA 检测；工作区磁盘单列 |
| CLI 看板 | `python -m prospect dashboard` | 真实状态快照；`--watch` 开启刷新与 r/s/q 操作 |
| 停止 | `python -m prospect stop` | 原生私有令牌停止，数据保留；隔离恢复测试有实测 |
| 单元/集成检查 | `python -B -m unittest discover -s tests -v` | evidence/tests-final.log |
| 真实进程验证 | `python -B scripts/verify-runtime.py` | 八客户端并发、单实例、端口冲突、崩溃恢复、状态保留；使用独立临时状态 |
| 浏览器检查 | `node scripts/browser-qa.mjs` | 自有服务与隔离 Chrome；需先启动独立 QA 浏览器，不能直接复用用户浏览器 |

旧项目基线从上一级执行 `python -B -m unittest test_radar`，19 项通过，见 evidence/legacy-tests.log。适配器相关检查的准确前提与范围在 adapters/evidence/，不能仅凭测试文件存在判断已通过。

## 日常使用

打开 `Open-Prospect.cmd` 或访问 http://127.0.0.1:18766/。未运行时执行 ensure。页面与 agent 都连接同一服务；退出终端面板不会停服务。来源有间隔与退避，因此重复点击扫描可能返回跳过，这是实际调度状态。

当前正式观察尚未开始。`observe start / pause / resume` 已提供，但七天验收应先冻结来源与检查窗口，补齐阶段前提并记录开始时间。程序不会把回放、单元测试或等待聊天的时间计作通过。24 小时窗口中的关机与暂停仍算覆盖缺口。

## 日志、停止与恢复

- 状态库：`%LOCALAPPDATA%\Prospect\prospect.sqlite3`。
- 服务日志：`%LOCALAPPDATA%\Prospect\service.log`；接口诊断和扫描在 SQLite 事件表。
- `control.json` 包含本机令牌，属于凭据；不复制到保存库、聊天或报告。异常退出后 ensure 可恢复，重启会轮换令牌。
- 若端口被其他程序占用，排查所属程序；不要终止未知进程。若要改端口，需停下当前服务并重新生成适配器。
- 当前没有登录 Windows 后的独立新启动任务；已启用宿主的启动钩子负责唤醒服务。原 MiningRadar 启动项仍保持原状。

## 卸载

先通过宿主插件管理界面禁用/卸载对应 Prospect 插件，再停止共享服务。不要删除整个宿主 plugins/extensions 目录。pi 的本项目目录可用 `python -m adapters.manage uninstall --destination 'C:\Users\yyx\.pi\agent\extensions\prospect'` 按所有权校验处理；此真实全局卸载本轮未执行，包装工具的等价隔离流程已验证。默认保留运行数据库。

## 下次 Codex 接续

读取根目录 README、STATUS、AGENTS，再读取当前阶段。优先补齐四宿主真实启动/恢复与 DSH 运行时识别；不要因已安装而直接勾选宿主验收。继续筛选官方来源，明确首条路线和机器要求，才实现项目配方与无副作用模拟。P3 后冻结观察计划，再启动 168 小时只读观察；P5 仍需要具体项目、资源、费用和交付对象的范围授权。

后续三个层次分别验收：可运行开发版、满足 alpha 的四端与单项目模拟、满足 v0.1 的单项目真实交付和每日调度。当前只完成第一个层次，不放宽原企划门槛。
