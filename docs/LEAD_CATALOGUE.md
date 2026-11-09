# 全部线索与保留依据

2026-11-09，FIND-01已完成本切片验证。左侧“全部线索”保留所有已存项目；“开挖待办”继续显示重点公告。72条线索全部可查，不表示72条都满足尚未开挖或值得运行。

## 已接通

- `GET /api/leads`：offset/limit分页，q关键词，stage发现阶段，category类型，compute设备方向；limit为1—50，返回total、matched、next_offset及全库阶段数量。
- `GET /api/leads/detail?id=...`：任何已存线索的详情，包括先前未公开展示的存档。沿用本机认证与Origin/Host保护，不返回私有租约或模型配置。
- 四端现有`prospect_candidates`工具改为查询全量目录，并增加相同筛选；`prospect_assess`可读取旧存档详情。共29工具，prepared-v13及五处已安装/marketplace桥接已更新；原生宿主模型验收限制保持。
- Web支持20条一页、搜索、阶段/类别/设备筛选、详情、历史报告及Agent检查入口。CLI仪表盘显示全量数量和前8条，同源工具提供完整分页。重点项目保持CPU优先、GPU其次。

## 阶段与依据

`unverified`保留未知、社区消息、已到公告时间但尚未证实开放、陈旧证据及旧线索；没有价格、钱包未知或硬件不匹配不会导致排除。`upcoming`需要一手主网未开放证据；`open`需要明确开放说明；`excluded`仅用于有一手取消/撤回依据的公告。用户“暂不跟进”不等于事实上的排除，Agent完成报告不等于安全通过。

历史成员通过一次性的`lead_catalog_history_v1`设置保留ID，候选原文、模型偏好、来源开关及观察记录不改写。旧记录未审查就写“历史存档，尚未逐项复核”；有旧报告则说明仍缺主网窗口或资料已变化，不能伪造逐项排除理由。该切片提供可追溯读取，自动官方核验及来源补抓仍属后续任务。

## 实际验证

- 私有SQLite基线、独立文件恢复核对及94个源码文件备份完成，`evidence/delivery-baseline.json`。没有替换生产库。
- 全量250项回归通过，126.907秒；新增目录与HTTP/CLI覆盖。`evidence/lead-catalogue-release-tests.log`，Headroom256→7行，估算节省9727tokens；7项目录专项短日志节省0。
- 正式服务分页读到72个唯一ID，其中待核实71、待开挖1、排除0，有完成报告4，重点待办1。原IDs、设置、检查记录保留，`evidence/lead-catalogue-runtime.json`。
- 四个生成桥接实际查询Humanity旧线索和详情，无模型调用；`evidence/lead-catalogue-four-adapters.json`。这不代替四个原生模型检查。
- 浏览器实测旧项目搜索、详情与检查入口、20条分页无交集、待开挖筛选、清除筛选；无控制台错误。390px下文档宽376px，过滤操作正常，标题改为纵向排布。`evidence/lead-catalogue-ui-qa.json`、`lead-catalogue-desktop.png`。手机截图在标题调整前曾成功，调整后截图接口失败；最终手机DOM/功能核对通过，最终视觉截图保留到FIND-07复核，旧图不作为最终布局证明。
- 两个接口各100次本机热读取：线索p95=153.9ms，检查状态p95=675.2ms。后者超过500ms目标，Q4保持partial，不宣称整体性能通过。`evidence/lead-catalogue-api-latency.json`。

主服务18766/PID36112；活动检查与项目执行均0，旧观察paused。本轮未开始付费研究、矿工、钱包操作或每日任务。日志仍为私有Prospect/service.log，停止用`py -3.12 -m prospect stop`。
