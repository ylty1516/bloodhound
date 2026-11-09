# 可见的 Agent 检查过程

2026-11-07。用户反馈无法判断检查是否真的进行，并且页面卡顿。检查发现：原生 CLI 的 communicate 等整个进程退出才解析输出；活跃检查每3秒读取完整状态并重建全部页面面板。现场完整状态约307KB、请求约0.8秒。

## 用户入口

“参与与运行”首屏先显示“我的 Agent 检查”，等待、进行中与最近结果集中展示；流程说明收进可展开区域。页首跟进入口跨页面保留。完成后直接查看结论；过程记录可展开，避免报告被说明和历史挤到下方。

显示内容来自实际状态：宿主、已等待/已用时、最近活动时间、最多五条近期事件、取消与查看结论。45秒无新活动时提示缺少活动回报，不把它写成失败；断线后保留最后状态并说明正在失联。关闭页面不取消检查，明确取消才停止任务。

## 服务与协议

- Codex 逐行读取 JSONL；Claude 使用 stream-json / verbose 并消费最后 result。stdout/stderr 同时排空，保留受限错误尾部用于静态分类，不保存原始日志。
- 只将允许的事件类型转换为固定中文阶段。搜索词、网页原文、模型思考、session ID 与凭据不会进入活动列表。没有上报的阶段不补造，不按时间推进虚构百分比。
- 本机进程每5秒检测一次；process_alive 表示进程存在，last_activity_at 表示实际接到活动。二者不互相替代。超时、取消、晚到结果和预算规则继续生效。
- 新增 prospect_check_progress 工具与 POST /api/checks/progress，四端共16工具。必须匹配 id / host / lease_token 且租约有效，只接受阶段枚举；网页Cookie不能回传进度。领取提示要求宿主在实际阶段变化时回报，不能用定时假进度代替工作。
- 老任务仅展示已保存的请求、领取和完成时间，不伪造过去的中间事件。Huddle01那次真实检查在北京时间00:00:49领取、00:04:18完成；本次修复未重复调用模型研究它。

## 刷新与交互

检查状态每2秒从轻量 /api/checks 同步，时钟每秒本地更新，不调用模型。完整状态仍每15秒同步；未变化的面板保留DOM，进度变化只更新检查区域。展开内容、焦点与表单保留，过时的完整响应不能覆盖较新的检查状态。本地服务重启后同源会话Cookie自动续接一次，持续失败则展示错误，不循环重试授权。

弹窗保持柔和反馈，将入场缩至160ms，关闭立即生效；移除背景模糊并统一为内容区滚动，减少多层滚动和重绘。减少动画偏好仍优先。

本机3样本：完整状态702–849ms、约307KB；轻量检查141–153ms、约18KB。这里比较轮询路径，不是Agent推理变快或全站性能保证。前后样本见 evidence/live-progress-before.json / live-progress-after.json。

## 验证与限制

108项完整Python回归通过；随后8项流式/租约与16项检查生命周期回归通过。四项JS验证覆盖会话续接、失败重试上限、保留未变化DOM和旧响应不能覆盖新任务。真实本地子进程管道覆盖提前输出、大stderr、超时、取消及Codex/Claude格式报告落库；这些是合成CLI输出，不冒充新的模型生成。

隔离IAB验证等待→领取→搜索→读取→整理→完成、长时间无活动提示、一键跟进与取消；主页面保留真实Huddle01结果。pi与DSH真实SDK加载16工具并成功查询状态/队列，均无模型调用。Claude真实生成与DSH完整宿主原有未验收项保持不变。

证据：live-progress-tests.log、live-progress-stream-final.log、live-progress-lifecycle-final.log、live-progress-js-check.json、live-progress-ui.json、adapters/evidence/pi-live-progress-session.json、dsh-live-progress-sdk.json。官方格式依据：[Codex JSONL](https://learn.chatgpt.com/docs/non-interactive-mode)、[Claude流式输出](https://code.claude.com/docs/en/headless)。
