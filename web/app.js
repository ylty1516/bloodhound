"use strict";

/* All API text is rendered through textContent. External links require HTTPS. */
const $ = (id) => document.getElementById(id);
const labels = {
  category: { pow: "传统挖矿", node: "节点 / 算力贡献", tasks: "测试网 / 空投任务" },
  participation: { open: "开放参与", closed: "已关闭", unknown: "尚待确认" },
  classification: { listed: "已存在现货交易", premarket: "存在盘前市场", unissued: "尚未发行", unlisted_supported: "有证据支持未上现货", conflict: "证据冲突", unknown: "市场状态待确认" },
  confidence: { low: "低", medium: "中", high: "高" },
  field: { ram_gb: "内存", disk_free_gb: "空闲存储", vram_gb: "显存", min_ram_gb: "最低内存", min_disk_gb: "最低存储", min_vram_gb: "最低显存", os: "操作系统", skill_level: "操作经验", daily_hours: "每日运行时长", available_minutes: "维护时间", gpu_allowed: "GPU 使用偏好", daily_cost: "每日成本", cpu_limit_pct: "CPU 配额", participation: "参与状态" },
  assessment: { compatible: "当前条件可匹配", incompatible: "存在不匹配条件", unknown: "适配信息不足" },
  observation: { not_started: "尚未开始", running: "观察中", paused: "已暂停", complete: "观察完成" },
  market: { token_issued: "代币已发行", tge: "已完成 TGE", mainnet: "主网已上线", transferable: "可转账", cex_spot: "CEX 现货交易", dex_spot: "DEX 现货交易", premarket: "盘前市场" },
  status: { not_checked: "尚未检查", success: "成功", ok: "正常", healthy: "正常", active: "运行中", pending: "等待检查", unknown: "尚待确认", error: "采集失败", failed: "失败", disabled: "已停用", idle: "等待采集", stale: "数据已过期", throttled: "采集限流", unchanged: "无内容变化", not_modified: "无内容变化", skipped: "已跳过", simulated: "模拟完成", simulation: "模拟", blocked: "预检未通过", mock: "模拟步骤", pass: "符合", fail: "不符合", ready: "就绪", running: "运行中", not_started: "尚未开始", complete: "已完成", verified: "已验证", unverified: "未验证", installed: "已安装", configured: "已配置", unavailable: "不可用", not_installed: "未安装", not_tested: "未实测", implemented: "接口已实现", contract_tested: "契约已测试", implemented_not_host_verified: "已实现 · 宿主未实测", native_verified: "原生宿主已验证", bridge_verified: "桥接已验证" },
};
const views = {
  overview: ["总览", "WORKSPACE OVERVIEW", "有价值的发现，值得你做决定。"],
  requests: ["开始参与", "PARTICIPATION", "设备方向、能否运行和下一步，直接看这里。"],
  opportunities: ["全部线索", "DISCOVERY INDEX", "完整查看每一条线索、核验状态与保留依据。CPU 优先，GPU 其次。"],
  todo: ["开挖待办", "LAUNCH WATCH", "发现后重点标记，提前核对公告与参与条件。"],
  runs: ["运行中心", "LIVE ACTIVITY", "看见每一步，随时停止，留下一份可核验的结果。"],
  evidence: ["来源与证据", "SOURCES & EVIDENCE", "结论可以追溯到来源，未知信息保持未知。"],
  settings: ["档案与设置", "WORKSPACE SETTINGS", "让适配评估基于你的设备、时间与维护能力。"],
  agents: ["Agent 与模型", "AGENT SETTINGS", "选择检查宿主、模型与思考强度，查看每次任务的真实记录。"],
};
const app = { state: null, fetching: false, lastSuccess: 0, lastError: "", selectedId: null, simulation: null, profileDirty: false, profileInitialized: false, pending: new Set(), toastTimer: null, observationAction: "start", selectedRequestId: null, seenRequests: new Set(), mutationRevision: 0 };
const GUIDE_VERSION = 1;
const GUIDE_STORAGE_KEY = "prospect_onboarding_v1";
const guideSteps = [
  {
    short: "准备", title: "先让系统核对收款与项目", route: "requests", action: "打开开始参与",
    description: "在“开始参与”点击“准备真实挖矿”。系统自动核对币安 Agent 钱包的收款网络、项目的交易证据和矿池门槛。",
    detail: "没有登录时，点击“连接币安钱包”，用币安 App 扫描官方二维码并核对配对码。收款地址自动读取，不需要填写私钥或助记词。",
    callout: "这里仅显示币安钱包能收款、且有交易价值证据的路线。可交易不代表挖矿能盈利。",
  },
  {
    short: "确认", title: "看清一轮会使用多少资源", route: "requests", action: "查看运行入口",
    description: "准备完成后，点击“开始 15 分钟真实挖矿”。确认页会列出收款、费用和本次 CPU、内存、时长上限。",
    detail: "当前路线在独立虚拟机里使用 2 条 CPU 线程，不启用 GPU。参数已经填好；第一次可以直接使用推荐范围。",
    callout: "只有点击最后的确认按钮才会启动这一轮。先看付款门槛，再决定是否尝试。",
  },
  {
    short: "跟进", title: "直接看它正在做哪一步", route: "runs", action: "查看运行中心",
    description: "启动、连接矿池、准备挖矿数据、实际算力和接受份额会陆续显示。运行中心保留实时日志、心跳和停止按钮。",
    detail: "接受份额为 0 时，可能仍在初始化或等待有效工作；页面会显示实际状态。关闭网页不会停止后台任务，达到时长上限会停止。",
    callout: "想结束本轮，直接点击“停止本轮”。不需要回到 Agent 聊天里输入命令。",
  },
  {
    short: "结果", title: "分清贡献、记账和真正到账", route: "requests", action: "查看本轮结果",
    description: "矿池接受了份额，才算有实际贡献；矿池余额增加，才算已记账。钱包到账还要核对付款交易、网络、资产和收款地址。",
    detail: "未达到矿池门槛时，收益会留在矿池。页面会明确显示尚未到账，结束后可以下载运行回执。请结合本轮实际收益判断后续安排。",
    callout: "当前入口是单轮运行。每日挖掘需要单独设置并授权。",
  },
];
const guide = { ...readGuideState(), returnFocus: null };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const entranceMotions = new Map();

function cancelEntrance(scope) {
  const animations = entranceMotions.get(scope);
  entranceMotions.delete(scope);
  animations?.forEach((animation) => {
    animation.onfinish = null;
    animation.oncancel = null;
    animation.cancel();
  });
}
function animateEntrance(scope, nodes) {
  cancelEntrance(scope);
  if (reducedMotion.matches || document.hidden) return;
  const visible = nodes.filter((node) => node?.getClientRects().length && typeof node.animate === "function").slice(0, 6);
  const animations = new Set();
  entranceMotions.set(scope, animations);
  visible.forEach((node, index) => {
    // Visual sequencing only: the route, focus and controls are already usable.
    const animation = node.animate([
      { opacity: .58, transform: "translateY(6px)" },
      { opacity: 1, transform: "translateY(0)" },
    ], { duration: 320, delay: Math.min(index * 35, 140), easing: "cubic-bezier(.2,.8,.2,1)", fill: "backwards" });
    animations.add(animation);
    animation.onfinish = animation.oncancel = () => {
      animations.delete(animation);
      if (!animations.size && entranceMotions.get(scope) === animations) entranceMotions.delete(scope);
    };
  });
  if (!animations.size) entranceMotions.delete(scope);
}
function cancelAllEntrances() {
  [...entranceMotions.keys()].forEach(cancelEntrance);
}
reducedMotion.addEventListener("change", () => { if (reducedMotion.matches) cancelAllEntrances(); });
document.addEventListener("visibilitychange", () => { if (document.hidden) cancelAllEntrances(); });
const array = (value) => Array.isArray(value) ? value : [];
const object = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
const hasValue = (value) => value !== undefined && value !== null && value !== "";
const display = (value, fallback = "尚待确认") => {
  if (!hasValue(value)) return fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};
const translated = (group, value, fallback = "尚待确认") => labels[group]?.[value] || display(value, fallback);
const finite = (value) => typeof value === "number" && Number.isFinite(value);
const number = (value, digits = 0) => finite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: digits }) : "待确认";
const date = (value, short = false) => {
  if (!hasValue(value)) return "尚无记录";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return display(value);
  return parsed.toLocaleString("zh-CN", short ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false } : { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
};
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = display(text, "");
  return node;
}
function append(parent, ...children) { children.filter(Boolean).forEach((child) => parent.append(child)); return parent; }
function setText(id, value) { $(id).textContent = display(value, ""); }
function readGuideState() {
  const initial = { version: GUIDE_VERSION, status: "new", step: 0, open: false };
  try {
    const saved = JSON.parse(localStorage.getItem(GUIDE_STORAGE_KEY) || "null");
    if (!saved || saved.version !== GUIDE_VERSION || !["new", "started", "skipped", "completed"].includes(saved.status)) return initial;
    if (!Number.isInteger(saved.step) || saved.step < 0 || saved.step >= guideSteps.length) return initial;
    return { version: GUIDE_VERSION, status: saved.status, step: saved.step, open: saved.open === true && ["started", "completed"].includes(saved.status) };
  } catch { return initial; }
}
function saveGuideState() {
  try {
    localStorage.setItem(GUIDE_STORAGE_KEY, JSON.stringify({ version: GUIDE_VERSION, status: guide.status, step: guide.step, open: guide.open }));
  } catch { /* Browsing and progress continue in this page when storage is unavailable. */ }
}
function renderGuideEntry() {
  $("guide-welcome").hidden = guide.status !== "new";
  $("guide-launch-state").hidden = !["started", "completed"].includes(guide.status);
  setText("guide-launch-state", guide.status === "completed" ? "已读" : `继续 ${guide.step + 1}/4`);
}
function renderGuide() {
  const completed = guide.status === "completed";
  const step = guideSteps[guide.step];
  setText("guide-title", completed ? "现在可以开始查看线索了" : step.title);
  setText("guide-description", completed ? "你已经读完使用指南。可以先去“发现项目”看看，遇到不熟悉的地方，再从右上角打开指南。" : step.description);
  setText("guide-detail", completed ? "读完指南只表示了解了使用流程。设备配置、项目核验和参与情况，仍以页面中的实际记录为准。" : step.detail);
  setText("guide-callout", completed ? "如果线索列表还是空的，可以自行点击页首“扫描公开来源”。等有符合条件的目标时，参与请求会提醒你。" : step.callout);
  setText("guide-page", completed ? "去看看项目线索" : step.action);
  setText("guide-page-note", completed ? "只打开项目列表，不会启动任务。" : "只查看页面，回来可以接着读。");
  setText("guide-step-count", completed ? "使用指南已读完" : `第 ${guide.step + 1} 步，共 ${guideSteps.length} 步`);
  $("guide-prev").hidden = completed;
  $("guide-prev").disabled = guide.step === 0;
  setText("guide-next", completed ? "回到工作台" : guide.step === guideSteps.length - 1 ? "读完了" : "下一步");
  $("guide-progress").replaceChildren(...guideSteps.map((item, index) => {
    const marker = element("li", `guide-step-marker${completed || index < guide.step ? " is-complete" : index === guide.step ? " is-current" : ""}`);
    if (!completed && index === guide.step) marker.setAttribute("aria-current", "step");
    const number = element("span", "guide-step-number", String(index + 1));
    number.setAttribute("aria-hidden", "true");
    return append(marker, number, element("span", "", item.short));
  }));
  $("guide-body").scrollTop = 0;
  renderGuideEntry();
  if ($("guide-dialog").open) animateEntrance("guide", [$("guide-description"), $("guide-detail"), $("guide-callout").parentElement, $("guide-page").parentElement]);
}
function openExclusiveDialog(id) {
  document.querySelectorAll("dialog[open]").forEach((dialog) => {
    if (dialog.id === id) return;
    if (dialog.id === "guide-dialog") closeGuide("cancel");
    else dialog.close("cancel");
  });
  if (!$(id).open) $(id).showModal();
}
function rememberGuideClosed() {
  cancelEntrance("guide");
  guide.open = false;
  saveGuideState();
  renderGuideEntry();
}
function closeGuide(reason = "dismiss") {
  rememberGuideClosed();
  $("guide-dialog").close(reason);
}
function openGuide({ restore = false } = {}) {
  guide.returnFocus = restore ? $("guide-launch") : document.activeElement;
  if (!restore && guide.status === "completed") guide.step = 0;
  if (!restore || guide.status !== "completed") guide.status = "started";
  guide.open = true;
  saveGuideState();
  renderGuide();
  openExclusiveDialog("guide-dialog");
  $("guide-title").focus({ preventScroll: true });
}
function moveGuide(direction) {
  guide.step = Math.max(0, Math.min(guideSteps.length - 1, guide.step + direction));
  saveGuideState();
  renderGuide();
  $("guide-title").focus({ preventScroll: true });
}
function statusTone(status) {
  if (["error", "failed", "fail", "incompatible", "conflict"].includes(status)) return "error";
  if (["blocked", "stale", "throttled", "premarket"].includes(status)) return "warning";
  if (["running", "success", "ok", "healthy", "open", "compatible", "verified", "native_verified", "bridge_verified", "complete", "simulated", "pass"].includes(status)) return "teal";
  return "";
}
function badge(text, tone = "") { return element("span", `badge ${tone}`.trim(), text); }
function statusBadge(value) { return badge(translated("status", value), statusTone(value)); }
function safeLink(url, text, className = "text-link") {
  try {
    const parsed = new URL(String(url));
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) return element("span", "muted", text || "链接不可用（仅接受 HTTPS）");
    const link = element("a", className, text || parsed.hostname);
    link.href = parsed.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.referrerPolicy = "no-referrer";
    link.setAttribute("aria-label", `${text || parsed.hostname}（在新标签页打开）`);
    return link;
  } catch { return element("span", "muted", text || "来源链接待确认"); }
}
function empty(title, copy, action) {
  const block = element("div", "empty-state");
  const symbol = element("span", "empty-symbol", "⌕");
  symbol.setAttribute("aria-hidden", "true");
  append(block, symbol, element("h3", "", title), element("p", "", copy));
  if (action) {
    const button = element("button", "button secondary small", action.label);
    button.type = "button";
    button.addEventListener("click", action.run);
    block.append(button);
  }
  return block;
}
function rawDetails(data, key, title = "查看完整记录") {
  const details = element("details", "raw-details");
  details.dataset.key = key;
  append(details, element("summary", "", title), element("pre", "", JSON.stringify(data, null, 2)));
  return details;
}
function definitionRow(label, value) {
  return append(element("div"), element("dt", "", label), element("dd", "", value));
}
function toast(message, isError = false) {
  clearTimeout(app.toastTimer);
  $("toast").textContent = message;
  $("toast").className = `toast${isError ? " error" : ""}`;
  $("toast").hidden = false;
  app.toastTimer = setTimeout(() => { $("toast").hidden = true; }, isError ? 8500 : 4500);
}

async function request(path, body, timeout = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const options = { credentials: "same-origin", cache: "no-store", signal: controller.signal, headers: { Accept: "application/json" } };
    if (body !== undefined) { options.method = "POST"; options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
    let response = await fetch(path, options);
    if(response.status===403 && path.startsWith("/api/")){
      // Re-establish the same-origin local cookie after a service restart. One retry only.
      app.renewSession ||= fetch("/",{credentials:"same-origin",cache:"no-store",signal:controller.signal}).finally(()=>{app.renewSession=null;});
      const renewed=await app.renewSession;
      if(renewed.ok)response=await fetch(path,options);
    }
    const content = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) throw new Error(content?.error || "本地会话授权失效，请通过 Prospect 的 ui 命令重新打开页面。");
      throw new Error(content?.error || `服务返回错误（${response.status}）`);
    }
    if (!content || typeof content !== "object") throw new Error("本地服务返回了无法识别的数据。");
    if (content.error) throw new Error(String(content.error));
    return content;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("本地服务响应超时，请检查服务是否仍在运行。");
    if (error instanceof TypeError) throw new Error("暂时无法连接本地服务，请检查服务是否仍在运行。");
    throw error;
  } finally { clearTimeout(timer); }
}
function renderConnection() {
  const stale = app.lastSuccess && Date.now() - app.lastSuccess > 45000;
  const failed = Boolean(app.lastError);
  $("connection-dot").className = `status-dot${failed ? " offline" : stale ? " stale" : !app.state ? " pending" : ""}`;
  setText("connection-label", failed ? "本地服务连接异常" : stale ? "数据需要刷新" : app.state ? "本地服务已连接" : "正在连接本地服务");
  $("connection-banner").hidden = !(failed || stale);
  $("connection-banner").className = `connection-banner${failed ? " error" : ""}`;
  setText("connection-message", failed ? `${app.lastError}${app.state ? " 当前保留上次同步的数据。" : ""}` : "超过 45 秒未收到新状态，当前显示上次同步的数据。");
  $("scan-button").disabled = !app.state || failed || app.pending.has("scan");
  $("save-profile-button").disabled = !app.state || failed || app.pending.has("profile");
  $("refresh-button").disabled = app.fetching;
  setText("last-updated", app.lastSuccess ? `最近同步 ${date(app.lastSuccess)} · 每 15 秒刷新` : "等待首次同步");
}
async function loadState({ initial = false } = {}) {
  if (app.fetching) return;
  app.fetching = true;
  const readRevision = app.mutationRevision;
  const checksRevision=app.checksRevision||0;
  renderConnection();
  try {
    const state = await request("/api/state");
    if (readRevision !== app.mutationRevision) return;
    if (!state.service || !Array.isArray(state.candidates)) throw new Error("本地服务的状态结构不完整，暂时无法展示。");
    if(checksRevision!==(app.checksRevision||0)){state.agent_checks=app.state.agent_checks;state.agent_budget=app.state.agent_budget;state.agent_context=app.state.agent_context;}
    app.state = state;
    app.lastSuccess = Date.now();
    app.lastError = "";
    renderAll();
    app.checkLastSuccess=Date.now();
    notifyParticipation();
  } catch (error) {
    app.lastError = error.message;
    if (!app.state) renderUnavailable();
    if (!initial && !app.state) toast(error.message, true);
  } finally { app.fetching = false; renderConnection(); }
}
function renderUnavailable() {
  ["metric-candidates", "metric-sources", "metric-cycles", "metric-usage", "observation-hours"].forEach((id) => setText(id, "待连接"));
  setText("metric-candidates-note", "连接后读取真实候选");
  setText("machine-name", "设备信息尚不可用");
  setText("observation-start", "连接本地服务后查看");
  ["recent-candidates", "candidate-list", "run-list", "scan-list", "source-list", "event-list", "participation-list", "participation-overview"].forEach((id) => {
    $(id).replaceChildren(empty("尚未连接本地服务", "这里会显示本地服务返回的真实记录。请检查服务状态后重试。", { label: "重试连接", run: () => loadState() }));
  });
}
function renderAll() {
  const expanded = new Set([...document.querySelectorAll("details[data-key][open]")].map((node) => node.dataset.key));
  const focusedId = document.activeElement?.id;
  const state=app.state;
  app.renderSignatures ||= {};
  const changed=(name,value,render)=>{const signature=JSON.stringify(value);if(app.renderSignatures[name]!==signature){app.renderSignatures[name]=signature;render();}};
  changed("overview",[state.candidates,state.lead_catalog?.total,state.hardware,state.sources,state.usage],renderOverview);
  renderObservation();
  changed("participation",[state.participation_requests,state.preparation_plans],renderParticipation);
  changed("candidates",[state.candidates,state.discovery_archive,state.agent_checks?.map(j=>[j.id,j.status,j.updated_at])],renderCandidates);
  changed("runs",[state.runs,state.scans],renderRuns);
  if(typeof renderExecutions==='function')renderExecutions();
  if(typeof renderLaunchWatch==='function')renderLaunchWatch();
  changed("sources",[state.sources,state.monitoring,state.observation.status],renderSources);
  changed("events",state.events,renderEvents);
  changed("settings",[state.profile,state.hardware,state.usage,state.agent_budget,state.host_compatibility],renderSettings);
  changed("deepseek",state.agent_settings?.deepseek_api,renderDeepSeek);
  changed("agentSettings",state.agent_settings,renderAgentModels);
  renderModelHistory();
  renderCheckCenter();
  if ($("candidate-dialog").open && app.selectedId) renderAgentCheck(app.selectedId);
  document.querySelectorAll("details[data-key]").forEach((node) => { node.open = expanded.has(node.dataset.key); });
  if (focusedId && document.activeElement === document.body) $(focusedId)?.focus({ preventScroll: true });
  setText("sidebar-version", `Prospect / ${display(app.state.service.version, "本地服务")}`);
  setText("nav-count", app.state.lead_catalog?.total ?? array(app.state.candidates).length);
}

async function loadChecks() {
  if(app.checkFetching || !app.state || document.hidden)return;
  app.checkFetching=true;const revision=app.mutationRevision;
  try{
    const result=await request("/api/checks",undefined,8000);
    if(revision!==app.mutationRevision)return;
    const old=JSON.stringify(array(app.state.agent_checks).map(j=>[j.id,j.status]));
    app.checksRevision=(app.checksRevision||0)+1;app.state.agent_checks=result.jobs;app.state.agent_check_hosts=result.hosts;app.state.agent_context=result.agent_context;
    if(result.budget)app.state.agent_budget=result.budget;
    app.checkLastSuccess=Date.now();app.checkLastError="";
    const openDetails=new Set([...document.querySelectorAll("details[data-key][open]")].map(n=>n.dataset.key));const focus=document.activeElement?.id;
    renderCheckCenter();renderModelHistory();
    if($("candidate-dialog").open&&app.selectedId)renderAgentCheck(app.selectedId);
    document.querySelectorAll("details[data-key]").forEach(n=>{n.open=openDetails.has(n.dataset.key);});
    if(focus&&document.activeElement===document.body)$(focus)?.focus({preventScroll:true});
    if(old!==JSON.stringify(result.jobs.map(j=>[j.id,j.status])))await loadState();
  }catch(error){app.checkLastError=error.message;}
  finally{app.checkFetching=false;updateCheckClocks();}
}

function checkDuration(start,end) {
  const seconds=Math.max(0,Math.floor(((end?new Date(end).getTime():Date.now())-new Date(start).getTime())/1000));
  if(!Number.isFinite(seconds))return "计时待同步";
  return seconds<60?`${seconds} 秒`:`${Math.floor(seconds/60)} 分 ${seconds%60} 秒`;
}
function updateCheckClocks() {
  document.querySelectorAll("[data-check-start]").forEach(n=>{n.textContent=`${n.dataset.checkLabel||"已用时"} ${checkDuration(n.dataset.checkStart,n.dataset.checkEnd)}`;});
  document.querySelectorAll("[data-check-activity]").forEach(n=>{
    const age=Math.max(0,Math.floor((Date.now()-new Date(n.dataset.checkActivity))/1000));
    n.textContent=`最近活动 ${age<3?"刚刚":age<60?`${age} 秒前`:`${Math.floor(age/60)} 分钟前`}`;
  });
  document.querySelectorAll("[data-check-watch]").forEach(n=>{
    const job=array(app.state?.agent_checks).find(j=>j.id===n.dataset.checkWatch);if(!job)return;
    const active=["queued","running"].includes(job.status);
    const quiet=(Date.now()-new Date(job.last_activity_at||job.claimed_at||job.created_at))/1000;
    const offline=app.checkLastError||((app.checkLastSuccess&&Date.now()-app.checkLastSuccess>15000)?"检查状态同步已中断":"");
    n.hidden=!active||(!offline&&quiet<45);
    n.textContent=offline?"暂时收不到检查状态，下面保留最近记录；恢复连接后会继续同步。":job.status==="queued"?"任务仍在等待领取，尚未开始核验。":job.process_alive?"暂时没有新的活动回报，进程仍在运行。可以继续等待，也可以取消检查。":"暂未收到新的活动，无法确认 Agent 当前做到哪一步；可以等待宿主回报或取消。";
  });
}
function checkProgressView(job) {
  const section=element("section","check-progress");
  const active=["queued","running"].includes(job.status);
  const meta=element("div","check-meta");
  append(meta,element("span","",checkHostLabels[job.host||job.requested_host]||"自动选择 Agent"));
  const elapsed=element("span");elapsed.dataset.checkLabel=job.claimed_at?"已用时":active?"已等待":"总耗时";elapsed.dataset.checkStart=job.claimed_at||job.created_at;elapsed.dataset.checkEnd=job.finished_at||(!active?job.updated_at:"");meta.append(elapsed);
  if(active&&job.last_activity_at){const last=element("span");last.dataset.checkActivity=job.last_activity_at;meta.append(last);}
  section.append(meta,element("p","check-current",job.progress||checkStatusLabels[job.status]));
  if(active){
    section.append(element("p","quiet-note",job.process_alive===true?"本机 Agent 进程运行中 · 活动自动同步":job.status==="queued"?"任务已保存，等待 Agent 领取。尚未开始检查。":job.method==="host_tools"?"已由宿主领取；下方只展示它实际回报的阶段。":"正在等待检查服务的活动回报。"));
    const warning=element("p","check-quiet");warning.dataset.checkWatch=job.id;warning.hidden=true;section.append(warning);
  }
  let history=array(job.activity);const legacy=!history.length;
  if(legacy)history=[{at:job.created_at,label:"检查请求已保存"},{at:job.claimed_at,label:"Agent 已领取任务"},{at:job.finished_at,label:job.status==="completed"?"检查报告已保存":"检查已结束"}].filter(event=>event.at);
  if(history.length){
    const timeline=element("ol","check-timeline");
    history.slice(-5).forEach(event=>{const li=element("li");const stamp=element("time","",new Date(event.at).toLocaleTimeString("zh-CN",{hour12:false,timeZone:"Asia/Shanghai"}));append(li,stamp,element("span","",event.label));timeline.append(li);});
    if(active)section.append(timeline);
    else{const details=element("details","check-history");details.dataset.key=`check-history-${job.id}`;append(details,element("summary","",legacy?"查看已保存的时间记录":"查看最近的过程记录"),timeline);section.append(details);}
  }
  if(legacy&&active)section.append(element("p","quiet-note","这次检查未保存中间活动，以上仅显示已有的时间记录。"));
  return section;
}
function openCheck(id) {
  const job=array(app.state?.agent_checks).find(j=>j.id===id);if(!job)return;
  app.focusedCheckId=id;app.checkHost=job.host||job.requested_host||"any";
  openCandidate(job.candidate_id);
}
function renderCheckCenter() {
  const jobs=array(app.state?.agent_checks);
  const signature=JSON.stringify(jobs.map(({heartbeat_at,...job})=>job));
  const container=$("check-center-list");
  if(container.dataset.state!==signature){
    container.dataset.state=signature;
    const active=jobs.filter(j=>["queued","running"].includes(j.status));
    const recent=jobs.filter(j=>!["queued","running"].includes(j.status)).slice(0,3);
    const cards=[...active,...recent].map(job=>{
      const card=element("article","check-card");const head=element("div","record-heading");
      const title=element("button","check-name",job.candidate_name);title.type="button";title.addEventListener("click",()=>openCheck(job.id));
      append(head,title,badge(checkStatusLabels[job.status]||job.status,job.status==="failed"?"warning":"teal"));card.append(head,checkProgressView(job));
      if(job.report){if(job.recommendation)card.append(badge(job.recommendation.label,job.recommendation.status==="suggested_trial"?"teal":""));card.append(element("p","check-summary",job.recommendation?.reason||job.report.summary));}
      const actions=element("div","detail-actions");const view=element("button","button secondary",job.status==="completed"?"查看检查结论":"查看进度与详情");view.type="button";view.id=`check-card-${job.id}`;view.addEventListener("click",()=>openCheck(job.id));actions.append(view);
      if(["queued","running"].includes(job.status)){const cancel=element("button","text-button","取消检查");cancel.type="button";cancel.id=`cancel-${job.id}`;cancel.addEventListener("click",()=>cancelAgentCheck(job.id));actions.append(cancel);}
      card.append(actions);return card;
    });
    const historyWasOpen=container.querySelector("details[data-key='recent-checks']")?.open;
    const nodes=cards.slice(0,active.length);
    if(recent.length){const history=element("details","recent-checks");history.dataset.key="recent-checks";history.open=Boolean(historyWasOpen);history.append(element("summary","",`最近 ${recent.length} 次检查 · 展开查看结果与过程`),...cards.slice(active.length));nodes.push(history);}
    container.replaceChildren(...(nodes.length?nodes:[empty("还没有发起检查","选择一个项目，交给 Agent 核验；每个阶段和最终结论都会显示在这里。",{label:"选择项目",run:()=>startParticipation()})]));
  }
  const bar=$("check-shortcut");const active=jobs.filter(j=>["queued","running"].includes(j.status));const job=active[0]||jobs[0];
  const barSignature=JSON.stringify(job?[job.id,job.status,job.progress,active.length]:null);
  bar.hidden=!job||(app.activeView==='requests'&&!active.length);
  if(bar.dataset.state!==barSignature){bar.dataset.state=barSignature;bar.replaceChildren();if(job){const text=element("span","",active.length?`${active.length} 个检查处理中 · ${job.candidate_name}`:`最近检查 · ${job.candidate_name}`);const button=element("button","text-button",active.length?"跟进检查":"查看结果");button.type="button";button.id="check-shortcut-open";button.addEventListener("click",()=>openCheck(job.id));append(bar,text,button);}}
  updateCheckClocks();
  if(typeof renderParticipationStart==='function')renderParticipationStart();
}
const participationLabels = { pending: "等待决定", interested: "已有参与意向", dismissed: "暂不参与", stale: "需要重新核验" };
function participationEmpty(compact = false) {
  const block = element("div", "request-empty");
  const content = element("div");
  append(content, element("h3", "", "还没有符合提请条件的项目"), element("p", "", "在本页上方选择项目并发起 Agent 检查。有明确建议后，参与请求会显示在这里。"));
  const flow = element("div", "request-flow");
  ["公开来源发现", "核实证据与适配", "提请你参与"].forEach(label => flow.append(element("span", "", label)));
  content.append(flow);
  if (!compact) { const link=element("a", "text-link", "选择待核验的项目 ↗");link.href="#opportunities";content.append(link); }
  append(block, content, element("span", "request-number", "0"));
  return block;
}
function requestCard(item, compact = false) {
  const card = element("article", `request-card ${item.status === "pending" ? "pending" : ""}`);
  const top = element("div", "request-card-top");
  const title = element("div");
  append(title, element("h3", "", display(item.candidate_name, "项目参与请求")), element("div", "request-meta", `${display(item.plan?.category_label, "待核验类型")} · 提请于 ${date(item.created_at, true)}`));
  append(top, title, badge(participationLabels[item.status] || "待核验", item.status === "pending" ? "teal" : ""));
  card.append(top);
  const reasons = element("ul", "request-reasons");
  array(item.reasons).slice(0, compact ? 3 : 6).forEach(reason => reasons.append(element("li", "", reason)));
  card.append(reasons);
  if (!compact) card.append(element("p", "", display(item.plan?.estimated_cost, "费用仍待确认")));
  const actions = element("div", "detail-actions");
  const review = element("button", `button ${item.status === "pending" ? "primary" : "secondary"}`, "查看参与计划");
  review.type="button"; review.id=`${compact ? "overview" : "inbox"}-request-${item.id}`;
  review.addEventListener("click", () => openParticipation(item.id));
  actions.append(review);
  if (compact) actions.append(element("span", "quiet-note", "先看计划，由你决定是否参与"));
  card.append(actions);
  return card;
}
function renderParticipation() {
  const items = array(app.state.participation_requests);
  const pending = items.filter(item => item.status === "pending");
  setText("nav-request-count", pending.length ? pending.length : "");
  setText("request-overview-count", pending.length);
  setText("participation-count", `${pending.length} 个等待决定 · 共 ${items.length} 个请求`);
  $("participation-overview").replaceChildren(pending.length ? requestCard(pending[0], true) : participationEmpty(true));
  if (pending.length > 1) {
    const more=element("a", "request-more text-link", `还有 ${pending.length - 1} 个请求待查看 ↗`);more.href="#requests";$("participation-overview").append(more);
  }
  if (!items.length) $("participation-list").replaceChildren(participationEmpty());
  else $("participation-list").replaceChildren(...[...items].sort((a,b)=>Number(b.status === "pending")-Number(a.status === "pending")).map(item => requestCard(item)));
  if ($("participation-dialog").open && app.selectedRequestId) {
    const active=items.find(item=>item.id===app.selectedRequestId);
    if(active) renderParticipationDetail(active);
  }
  renderPreparations();
}
const preparationLabels={not_recommended:"当前不建议参与",needs_information:"需要补齐条件",ready_for_simulation:"可以模拟准备流程"};
function auditView(advice) {
  const block=element("div","audit-summary");const audit=advice.audit;
  if(audit){append(block,element("p","quiet-note",`${audit.method==="official_web"?"官方网页步骤核验":"检查版本："+(audit.version||"尚未固定")} · 范围：${audit.scope||"尚未记录"}`));array(audit.findings).forEach(f=>block.append(element("p","",f)));array(audit.sources).forEach((url,i)=>block.append(safeLink(url,`安全依据 ${i+1} ↗`,"text-link")));}
  if(array(advice.notes).length){const notes=element("details","check-history");append(notes,element("summary","","硬件、费用与其他提示（不直接否决尝试）"));const list=element("ul","agent-next");advice.notes.forEach(n=>list.append(element("li","",n)));notes.append(list);block.append(notes);}
  return block;
}
function renderTrials(plans) {
  const latest=[...new Map([...plans].reverse().map(p=>[p.candidate_id,p])).values()];
  const suggested=latest.filter(p=>p.recommendation?.status==="suggested_trial");
  const container=$("trial-list");container.replaceChildren();
  if(!suggested.length)container.append(empty("还没有完成安全核验的条目","硬件不会筛掉项目。现有报告尚未提供可用于推荐的安全通过记录，待核验与已发现的问题分别列在下方。"));
  suggested.forEach(plan=>{const card=element("article","trial-card");append(card,element("h3","",plan.candidate_name),element("p","",plan.recommendation.reason),auditView(plan.recommendation));const button=element("button","button primary","查看尝试方案");button.type="button";button.id=`try-${plan.id}`;button.addEventListener("click",()=>openPreparation(plan.id));card.append(button);container.append(card);});
}
function preparationReason(value) {return String(value).replace(/条件待确认：([a-z_]+)/g,(_,key)=>`条件待确认：${translated("field",key)}`);}
function renderPreparations() {
  const plans=array(app.state.preparation_plans);
  renderTrials(plans);
  $("preparation-list").replaceChildren(...(plans.length ? plans.map(plan=>{
    const card=element("article","record");const head=element("div","record-heading");
    append(head,element("strong","",plan.candidate_name),badge(plan.recommendation?.label||preparationLabels[plan.status]||plan.status,plan.recommendation?.status==="suggested_trial"?"teal":""));
    const button=element("button","button secondary","查看准备方案");button.type="button";button.id=`plan-${plan.id}`;button.addEventListener("click",()=>openPreparation(plan.id));
    append(card,head,element("p","",plan.recommendation?.reason||plan.summary),element("p","quiet-note",plan.status==="ready_for_simulation"?"已有可模拟的固定版本配方":"运行准备单独评估，可展开查看设备、费用与配方安排。"),button);return card;
  }):[empty("还没有检查报告","完成一次 Agent 检查后，这里会显示对应的准备方案。") ]));
  if($("participation-dialog").open && app.selectedPlanId) {
    const plan=plans.find(p=>p.id===app.selectedPlanId);if(plan)renderPreparationDetail(plan);
  }
}
function openPreparation(id) {
  const plan=array(app.state.preparation_plans).find(p=>p.id===id);if(!plan)return;
  app.selectedRequestId=null;app.selectedPlanId=id;renderPreparationDetail(plan);openExclusiveDialog("participation-dialog");
}
function renderPreparationDetail(plan) {
  setText("participation-eyebrow","PREPARATION PLAN");
  setText("participation-title",plan.candidate_name);
  const body=$("participation-detail");const signature=JSON.stringify([plan,app.planSimulation,app.pending.has("rehearsal")]);
  if(body.dataset.preparation===signature)return;body.dataset.preparation=signature;body.replaceChildren();
  append(body,badge(plan.recommendation?.label||preparationLabels[plan.status]||plan.status,"teal"),element("p","",plan.recommendation?.reason||plan.summary));
  if(plan.recommendation)body.append(auditView(plan.recommendation));
  const original=element("details","agent-report-details");original.dataset.key=`plan-original-${plan.id}`;append(original,element("summary","","查看原始报告结论"),element("p","",plan.summary),element("p","quiet-note",plan.fact_sync.reason));body.append(original);
  const simulate=element("button","button primary",app.pending.has("rehearsal")?"正在检查方案…":"验证准备流程（模拟）");simulate.type="button";simulate.id="plan-simulate";simulate.disabled=app.pending.has("rehearsal");simulate.addEventListener("click",()=>simulatePlan(plan.id));body.append(simulate);
  body.append(element("p","quiet-note","模拟只验证步骤衔接，不启动项目。试运行会单独展示范围与资源上限。"));
  if(array(plan.execution_drivers).length){const run=element('button','button primary','设置并启动试运行');run.type='button';run.id='plan-execute';run.addEventListener('click',()=>openExecution(plan));body.prepend(run);}
  else body.append(element('p','quiet-note','这个项目的执行配方尚未接入。运行中心可以先做本机自检。'));
  if(plan.blockers.length){
    body.append(element("h3","","开始前还需要"));const list=element("ul","agent-next");plan.blockers.slice(0,3).forEach(x=>list.append(element("li","",preparationReason(x))));body.append(list);
    if(plan.blockers.length>3){const more=element("details","raw-details");more.dataset.key=`plan-blockers-${plan.id}`;more.append(element("summary","",`另外 ${plan.blockers.length-3} 项待确认`));const rest=element("ul","agent-next");plan.blockers.slice(3).forEach(x=>rest.append(element("li","",preparationReason(x))));more.append(rest);body.append(more);}
  }
  const recipe=plan.recipe;
  body.append(element("h3","",recipe?recipe.name:"项目配方尚未就绪"));
  if(recipe){
    body.append(element("p","quiet-note",`${recipe.version} · ${recipe.network} · ${recipe.artifact.locally_verified?"发布包已核对":"发布包尚未本机验证"}`));
    const steps=element("ol","simulation-steps");recipe.steps.forEach(s=>{const item=element("li","simulation-step");append(item,element("strong","",s.description),element("p","quiet-note",s.verification));steps.append(item);});body.append(steps);
    const details=element("details","raw-details");details.dataset.key=`recipe-${plan.id}`;append(details,element("summary","","版本、来源与限制"),safeLink(recipe.artifact.url,"发布包来源 ↗"),element("p","quiet-note",`SHA-256 ${recipe.artifact.sha256}`));recipe.limitations.forEach(x=>details.append(element("p","",x)));body.append(details);
  }else body.append(element("p","quiet-note","先补齐官方软件版本、发布校验与成果验证方式，再形成这个项目的模拟步骤。"));
  if(app.planSimulation?.plan_id===plan.id){const run=app.planSimulation;body.append(element("h3","",run.status==="simulated"?"模拟流程通过":run.status==="failed"?"模拟中断":"方案尚未满足条件"));array(run.blockers).forEach(x=>body.append(element("p","quiet-note",x)));body.append(simulationContent(run,`plan-run-${run.id}`));}
}
async function simulatePlan(id) {
  if(app.pending.has("rehearsal"))return;app.pending.add("rehearsal");renderPreparations();
  const fingerprint=array(app.state.preparation_plans).find(p=>p.id===id)?.fingerprint;
  app.rehearsalKeys ||= {};if(app.rehearsalKeys[id]?.fingerprint!==fingerprint)app.rehearsalKeys[id]={fingerprint,key:`web_${Date.now()}_${Math.random().toString(36).slice(2,9)}`};
  try{app.planSimulation=await request("/api/plans/simulate",{plan_id:id,key:app.rehearsalKeys[id].key});app.mutationRevision++;await loadState();}
  catch(error){toast(error.message,true);}finally{app.pending.delete("rehearsal");renderPreparations();}
}
function notifyParticipation() {
  const pending = array(app.state.participation_requests).filter(item=>item.status === "pending");
  try { const saved = JSON.parse(localStorage.getItem("prospect_participation_seen") || "[]"); if(Array.isArray(saved)) saved.forEach(id=>app.seenRequests.add(id)); } catch {}
  const unseen=pending.filter(item=>!app.seenRequests.has(item.id));
  if (!unseen.length) return;
  unseen.forEach(item=>app.seenRequests.add(item.id));
  try { localStorage.setItem("prospect_participation_seen", JSON.stringify([...app.seenRequests].slice(-2000))); } catch {}
  toast(`发现 ${unseen.length} 个值得进一步参与的目标。请到“参与与运行”查看证据、资源与费用计划。`);
}
function openParticipation(id) {
  app.selectedPlanId=null;delete $("participation-detail").dataset.preparation;
  const item=array(app.state?.participation_requests).find(item=>item.id===id);
  if (!item) return toast("请求已更新，请刷新后再查看。", true);
  app.selectedRequestId=id;
  renderParticipationDetail(item);
  openExclusiveDialog("participation-dialog");
  $("participation-detail").scrollTop=0;
}
function renderParticipationDetail(item) {
  setText("participation-eyebrow","PARTICIPATION REQUEST");
  setText("participation-title", display(item.candidate_name, "参与计划"));
  const body=$("participation-detail"), plan=object(item.plan);
  body.replaceChildren();
  const decisionNote = element("div", "request-decision-note");
  decisionNote.id = "participation-decision-state";
  const saving = app.pending.has(`request-${item.id}`) && item.status === "pending";
  append(decisionNote, badge(saving ? "正在保存决定" : participationLabels[item.status] || "待核验", item.status === "interested" ? "teal" : ""),
    element("p", "", saving ? "正在向本地服务保存你的决定，没有启动任务。" : item.status === "interested" ? "已记录参与意向，没有启动任务。可以打开准备方案，查看是否已有可执行路线，再设置本次运行范围。" : item.status === "dismissed" ? "已记录暂不参与。此请求保留在历史中，没有启动任务。" : item.status === "stale" ? "此请求需要重新核验。来源或适配条件已变化，当前不能确认参与。" : "这是参与意向请求。此处只保存决定；从准备方案设置并启动一次运行。"));
  body.append(decisionNote);
  const reasons=detailSection("为什么提请你参与");
  const reasonList=element("ul", "assessment-reasons");array(item.reasons).forEach(reason=>reasonList.append(element("li", "", reason)));reasons.append(reasonList);body.append(reasons);
  const details=detailSection("资源、时间与费用");
  const resources=element("dl", "request-plan-summary");
  array(plan.resources).forEach(resource=>resources.append(definitionRow(display(resource.name, "资源"), display(resource.value))));
  append(resources, definitionRow("每日运行", display(plan.runtime)),definitionRow("维护投入",display(plan.maintenance)),definitionRow("技能要求",display(plan.required_skill)),definitionRow("预计费用",display(plan.estimated_cost)));
  details.append(resources);body.append(details);
  const delivery=detailSection("预期交付与奖励");
  append(delivery, element("p", "detail-summary", display(plan.delivery, "交付成果仍需具体约定。")),element("p", "detail-subtitle",display(plan.reward,"奖励类型和兑现条件尚待确认。")));body.append(delivery);
  const unknowns=[...new Set([...array(plan.unknowns),...array(item.blockers)])];
  if (unknowns.length) {
    const blockers=detailSection("执行前仍需确认");const list=element("ul", "request-blockers");unknowns.forEach(text=>list.append(element("li", "",text)));blockers.append(list);body.append(blockers);
  }
  const evidence=detailSection("核验依据");
  if(!array(item.evidence).length) evidence.append(element("p", "detail-subtitle", "请求未提供可查看的来源证据。"));
  array(item.evidence).forEach((entry,index)=>{
    const data=object(entry);const row=element("div", "request-evidence");
    append(row,safeLink(data.url,display(data.title || data.kind,`来源 ${index+1}`)),element("p","detail-subtitle",display(data.note || data.summary,"查看一手来源核对条件。")),element("p","request-meta",`核验于 ${date(data.checked_at)}`));evidence.append(row);
  });body.append(evidence);
  if (item.status === "pending") {
    const actions=element("section","detail-action-panel");const buttons=element("div","detail-actions");
    for(const [decision,label,cls] of [["interested","有意参与","primary"],["dismissed","暂不参与","secondary"]]){
      const button=element("button",`button ${cls}`,label);button.type="button";button.id=`decision-${decision}`;button.disabled=app.pending.has(`request-${item.id}`);button.addEventListener("click",()=>decideParticipation(item.id,decision));buttons.append(button);
    }
    append(actions,buttons,element("p","quiet-note",display(plan.execution_note,"确认意向不会启动任务；执行前仍需配方与具体范围确认。")));body.append(actions);
  }
  body.append(rawDetails(item,`participation-${item.id}`,"查看完整请求记录"));
}
async function decideParticipation(id, decision) {
  const key=`request-${id}`;
  if(app.pending.has(key))return;
  app.pending.add(key);
  const current=array(app.state.participation_requests).find(item=>item.id===id);
  if(current)renderParticipationDetail(current);
  try {
    const receipt = await request("/api/participation/decision",{id,decision});
    if (receipt.id !== id || receipt.status !== decision) throw new Error("服务未确认该决定，请刷新后核对。");
    app.mutationRevision += 1;
    app.state.participation_requests = array(app.state.participation_requests).map(item => item.id === id ? receipt : item);
    renderParticipation();
    toast(decision === "interested" ? "已记录参与意向，没有启动任务。" : "已记录暂不参与。");
    await loadState();
    if ($("participation-dialog").open) $("close-participation").focus({ preventScroll: true });
  } catch(error){toast(error.message,true);}
  finally {
    app.pending.delete(key);
    const updated=array(app.state.participation_requests).find(item=>item.id===id);
    if(updated && $("participation-dialog").open)renderParticipationDetail(updated);
  }
}
function renderOverview() {
  const state = app.state;
  const candidates = array(state.candidates);
  const sources = array(state.sources);
  const observation = object(state.observation);
  const usage = object(state.usage);
  ["metric-candidates", "metric-sources", "metric-cycles", "metric-usage"].forEach((id) => $(id).classList.remove("loading-value"));
  setText("metric-candidates", state.lead_catalog?.total ?? candidates.length);
  setText("metric-candidates-note", `${array(state.launch_watch?.items).filter(item=>item.critical).length} 个重点待办 · 其余线索完整保留`);
  setText("metric-sources", sources.filter((s) => s.enabled).length);
  setText("metric-sources-note", `共 ${sources.length} 个已配置来源`);
  setText("metric-cycles", number(observation.cycles));
  setText("metric-cycles-note", `成功 ${number(observation.successes)} 次 · 真实运行累计`);
  setText("metric-usage", number((usage.agent_check_sessions || 0) + (usage.agent_check_host_reports || 0)));
  setText("metric-usage-note", "主动检查用量另计；规则巡检不调用模型");
  renderObservation();
  const hardware = object(state.hardware);
  setText("machine-name", display(hardware.cpu_name, "CPU 信息尚未探测"));
  const gpuNames = array(hardware.gpus).map((gpu) => typeof gpu === "string" ? gpu : display(gpu.name || gpu.model, "未知 GPU")).join(" / ");
  $("machine-summary").replaceChildren(
    definitionRow("操作系统", display(hardware.os, "尚未探测")),
    definitionRow("内存", finite(hardware.ram_gb) ? `${number(hardware.ram_gb, 1)} GB` : "尚未探测"),
    definitionRow("可用存储", finite(hardware.disk_free_gb) ? `${number(hardware.disk_free_gb, 1)} GB` : "尚未探测"),
    definitionRow("GPU", gpuNames || "尚未探测")
  );
  $("recent-candidates").replaceChildren(candidates.length ? candidateTable(candidates.slice(0, 5), true) : empty("还没有候选项目", "启用来源后运行一次扫描。只有实际采集到的项目才会出现在这里。", { label: "检查来源配置", run: () => { location.hash = "evidence"; } }));
}
function renderObservation() {
  const observation = object(app.state.observation);
  const status = observation.status || "not_started";
  const target = finite(observation.target_hours) && observation.target_hours > 0 ? observation.target_hours : 168;
  const elapsed = finite(observation.elapsed_hours) ? Math.max(0, observation.elapsed_hours) : 0;
  setText("observation-badge", translated("observation", status));
  $("observation-badge").className = `badge ${statusTone(status)}`.trim();
  setText("observation-hours", number(elapsed, 1));
  setText("observation-target", number(target));
  $("observation-progress").max = target;
  $("observation-progress").value = Math.min(elapsed, target);
  setText("observation-start", observation.start_at ? `开始于 ${date(observation.start_at, true)}` : "尚未开始持续观察");
  setText("observation-coverage", `覆盖率 ${number(observation.coverage_pct, 1)}${finite(observation.coverage_pct) ? "%" : ""}`);
  const action = status === "running" ? "pause" : status === "paused" ? "resume" : "start";
  app.observationAction = action;
  setText("observation-button", app.pending.has("observation") ? "正在更新…" : status === "complete" ? "七日观察已完成" : ({ pause: "暂停观察", resume: "继续观察", start: "开始观察" })[action]);
  $("observation-button").disabled = status === "complete" || app.pending.has("observation") || Boolean(app.lastError);
}
function candidateTable(candidates, compact = false) {
  const table = element("table", "data-table");
  table.setAttribute("aria-label", compact ? "最近发现的候选项目" : "候选项目列表");
  const thead = element("thead");
  const heading = element("tr");
  [["项目", "project-cell", "38%"], ["CPU / GPU", "hide-mobile", "19%"], ["能否运行", "status-cell", "25%"], ["下一步", "action-cell", "18%"]].forEach(([text, cls, width]) => {
    const th = element("th", cls, text);
    th.scope = "col"; th.style.width = width;
    if (!text) append(th, element("span", "sr-only", "操作"));
    heading.append(th);
  });
  thead.append(heading);
  const tbody = element("tbody");
  candidates.forEach((candidate) => {
    const row = element("tr");
    const nameCell = element("td", "project-cell");
    const name = element("button", "project-name-button", display(candidate.name, "未命名项目"));
    name.type = "button";
    name.id = `${compact ? "recent" : "candidate"}-name-${candidate.id}`;
    name.title = name.textContent;
    name.addEventListener("click", () => openCandidate(candidate.id));
    const nameWrap = element("span", "project-name"); nameWrap.append(name);
    append(nameCell, nameWrap, element("span", "project-subtitle", display(candidate.summary, "尚无项目摘要")));
    const compute=candidate.compute_profile;const launch=candidate.launch;
    nameCell.append(element('span','project-device-mobile',compute?.label||'设备待确认'));
    const typeCell = element("td", "hide-mobile table-meta",compute?.label||'设备待确认');typeCell.title=compute?.reason||'等待检查';
    const statusCell = element("td", "status-cell");
    statusCell.append(badge(launch?.status==='not_integrated'?'仅线索 · 不能启动':launch?.label||'等待核验',launch?.can_configure?'teal':''));
    const actionCell = element("td", "action-cell");
    const action = element("button", "button secondary candidate-action",launch?.status==='not_integrated'?'查看资料':launch?.can_configure?'设置运行':'看准备状态'); action.type = "button";
    action.id = `${compact ? "recent" : "candidate"}-action-${candidate.id}`;
    action.setAttribute("aria-label", `${action.textContent}：${display(candidate.name, "项目")}`);
    action.addEventListener("click", () => launch?.status==='not_integrated'?openCandidate(candidate.id):startParticipation(candidate.id));
    actionCell.append(action);
    append(row, nameCell, typeCell, statusCell, actionCell); tbody.append(row);
  });
  return append(table, thead, tbody);
}
function renderCandidates() {
  if(typeof renderLeadExplorer==='function')renderLeadExplorer();
}
function openCandidate(id) {
  const candidate = typeof leadCandidate==='function'?leadCandidate(id):array(app.state?.candidates).find((item) => item.id === id);
  if (!candidate) { toast("项目当前不可用，请刷新后重试。", true); return; }
  app.selectedId = id;
  app.simulation = null;
  setText("detail-title", display(candidate.name, "项目详情"));
  $("detail-title").title = display(candidate.name, "项目详情");
  renderCandidateDetail(candidate);
  openExclusiveDialog("candidate-dialog");
  $("candidate-detail").scrollTop = 0;
}
function detailSection(title) {
  return append(element("section", "detail-section"), element("h3", "", title));
}
function renderCandidateDetail(candidate) {
  const body = $("candidate-detail"); body.replaceChildren();
  const badges = element("div", "detail-badges");
  append(badges, badge(translated("category", candidate.category)), badge(translated("participation", candidate.participation), statusTone(candidate.participation)), badge(translated("classification", candidate.classification), statusTone(candidate.classification)));
  append(body, badges, element("p", "detail-summary", display(candidate.summary, "尚无项目摘要。")), safeLink(candidate.url, "查看项目公开主页 ↗"));
  if(candidate.lead_info){
    const info=candidate.lead_info,why=element('section','lead-explanation');
    why.append(element('h3','',info.stage_label+' · 保留依据'),element('p','',info.reason));
    if(info.review_summary)why.append(element('p','','历史 Agent 报告：'+info.review_summary));
    for(const url of array(info.reason_sources))why.append(safeLink(url,'查看阶段判断的来源 ↗'));
    body.insertBefore(why,body.children[1]);
  }
  const market = detailSection("市场阶段");
  market.append(element("p", "detail-subtitle", `证据置信度：${translated("confidence", candidate.confidence)} · 最近核对：${date(candidate.checked_at)}。未知不等于未开盘。`));
  const marketGrid = element("dl", "market-grid");
  Object.entries(labels.market).forEach(([key, label]) => {
    const value = ({ yes: "是", no: "否", unknown: "尚待确认" })[candidate.market?.[key]] || "尚待确认";
    marketGrid.append(append(element("div", "market-item"), element("dt", "", label), element("dd", "", value)));
  });
  market.append(marketGrid); body.append(market);
  const assessment = object(candidate.assessment);
  const fit = detailSection("与你的设备和能力匹配");
  fit.append(badge(translated("assessment", assessment.status), statusTone(assessment.status)));
  if (array(assessment.reasons).length) {
    const reasons = element("ul", "assessment-reasons");
    assessment.reasons.forEach((reason) => reasons.append(element("li", "", reason))); fit.append(reasons);
  }
  if (array(assessment.checks).length) fit.append(rawDetails(assessment.checks, `checks-${candidate.id}`, "查看逐项匹配依据"));
  if (array(assessment.missing).length) fit.append(element("p", "detail-subtitle", `仍缺少：${assessment.missing.map((field) => translated("field", field)).join("、")}`));
  fit.append(element("p", "detail-subtitle", "适配不代表能够获利。当前版本不估算未定价奖励的现金收益。"));
  body.append(fit);
  const requirements = detailSection("项目要求与奖励单位");
  const req = object(candidate.requirements);
  const reqList = element("dl", "detail-definition");
  append(reqList, definitionRow("最低内存", finite(req.min_ram_gb) ? `${number(req.min_ram_gb, 1)} GB` : "尚待确认"), definitionRow("最低存储", finite(req.min_disk_gb) ? `${number(req.min_disk_gb, 1)} GB` : "尚待确认"), definitionRow("最低显存", finite(req.min_vram_gb) ? `${number(req.min_vram_gb, 1)} GB` : "尚待确认"), definitionRow("操作系统", Array.isArray(req.os) ? req.os.join(" / ") || "尚待确认" : display(req.os)), definitionRow("奖励单位", display(candidate.reward_unit)));
  requirements.append(reqList); body.append(requirements);
  const evidence = detailSection("来源证据");
  if (array(candidate.evidence).length) {
    const list = element("ul", "evidence-list");
    candidate.evidence.forEach((item, index) => {
      const data = typeof item === "string" ? { note: item } : object(item);
      const li = element("li");
      const title = display(data.title || data.kind, `证据 ${index + 1}`);
      li.append(data.url ? safeLink(data.url, title, "evidence-title") : element("span", "evidence-title", title));
      append(li, element("p", "", display(data.note || data.summary, "未提供说明")), element("p", "", `核对时间：${date(data.checked_at)}`), rawDetails(data, `evidence-${candidate.id}-${index}`, "查看证据字段"));
      list.append(li);
    }); evidence.append(list);
  } else evidence.append(element("p", "detail-subtitle", "尚无可追溯证据，当前不能确认项目市场阶段。"));
  body.append(evidence);
  const technical=element('details','project-technical');technical.append(element('summary','','市场、设备要求与完整来源'),market,fit,requirements,evidence);body.append(technical);
  const actions = element("section", "detail-action-panel candidate-start");
  actions.append(element("h3", "", candidate.launch?.label||"检查项目资料"));
  if(candidate.compute_profile)actions.append(badge(candidate.compute_profile.label,candidate.compute_profile.basis==='discovery_hint'?'':'teal'),element('p','quiet-note',candidate.compute_profile.reason));
  actions.append(element('p','',candidate.launch?.reason||'先核验项目资料，再判断运行条件。'),element('p','quiet-note','下面的检查用于核对资料，不代表启动程序已经接入。'));
  const review = element("div", "agent-check-panel"); review.id = "agent-check-panel"; actions.append(review);
  const buttons = element("div", "detail-actions");
  const simulate = element("button", "button secondary", "仅做本地规则预检");
  simulate.id = "simulate-button"; simulate.type = "button";
  simulate.addEventListener("click", () => simulateCandidate(candidate.id));
  const entry = element("button", "button secondary", candidate.prelaunch?"在开挖待办中跟进":"查看完整参与流程");
  entry.type = "button";
  entry.addEventListener("click", () => { $("candidate-dialog").close(); location.hash = candidate.prelaunch?"todo":"requests"; });
  append(buttons, simulate, entry);
  append(actions, buttons, element("p", "quiet-note", "预检不会安装、挖矿或产生奖励。真实执行还需要开发并验证项目配方与运行器，再确认具体参与范围。"));
  const result = element("div"); result.id = "simulation-result"; actions.append(result); body.insertBefore(actions, body.children[candidate.lead_info?2:1]);
  renderAgentCheck(candidate.id);
}

const checkHostLabels = {codex:"Codex", claude:"Claude Code", pi:"pi", deepseek:"DeepSeek Harness", deepseek_api:"DeepSeek API", any:"自动选择"};
const checkStatusLabels = {queued:"等待 Agent 领取", running:"Agent 检查中", completed:"Agent 检查完成", failed:"检查未完成", cancelled:"已取消检查", stale:"资料变化，需要重检",budget_blocked:"该次检查受当时预算限制"};
const checkTopicLabels = {identity:"项目与仓库身份", availability:"参与窗口与资格", market:"发行与交易状态", hardware:"本机硬件", effort:"技能与维护时间", cost:"费用与预算", risk:"风险与限制"};
function renderAgentCheck(candidateId) {
  const panel = $("agent-check-panel");
  if (!panel) return;
  const hosts = array(app.state?.agent_check_hosts);
  const chosen = app.checkHost || "current";
  const job = array(app.state?.agent_checks).find(j=>j.id===app.focusedCheckId&&j.candidate_id===candidateId) || array(app.state?.agent_checks).find(j => j.candidate_id === candidateId && (["any","current"].includes(chosen) || j.host === chosen || j.requested_host === chosen));
  const {heartbeat_at,...stableJob}=job||{};
  const signature = JSON.stringify([hosts, app.state.agent_context, stableJob, chosen, app.pending.has("agent-check"),app.state.agent_budget,array(app.state.preparation_plans).filter(p=>p.candidate_id===candidateId).map(p=>p.id)]);
  if (panel.dataset.state === signature) return;
  panel.dataset.state = signature;
  panel.replaceChildren();
  const active = job && ["queued", "running"].includes(job.status);
  const cached = job?.current && job.status === "completed" && job.model_fingerprint === app.state.agent_settings?.fingerprint && Date.now()/1000 - job.created_epoch < 86400;
  const controls = element("div", "agent-check-controls");
  const label = element("label", "", "检查 Agent"); label.htmlFor = "agent-check-host";
  const select = element("select"); select.id = "agent-check-host";
  const currentAgent=app.state.agent_context;
  const automatic = element("option", "", currentAgent?.status==="detected"?`自动识别 · ${currentAgent.label}`:"自动识别 · 等待 Agent 连接"); automatic.value="current"; select.append(automatic);
  hosts.forEach(host => { const option=element("option", "", `${host.label} · ${["native_cli","provider_api"].includes(host.dispatch) ? "可直接调用" : host.dispatch==="not_configured" ? "需配置接口" : "需宿主领取"}`); option.value=host.id; select.append(option); });
  select.value = app.checkHost || "current"; select.disabled = Boolean(active);
  select.addEventListener("change", () => { app.focusedCheckId=null;app.checkHost = select.value; renderAgentCheck(candidateId); $("agent-check-host")?.focus(); });
  const start = element("button", "button primary", app.pending.has("agent-check")?"正在提交检查…":active ? "Agent 正在检查…" : cached ? "已完成 Agent 检查" : job?.status === "failed" ? "重试 Agent 检查" : "交给 Agent 检查");
  start.id="agent-check-start"; start.type="button"; start.disabled=Boolean(active || cached || app.pending.has("agent-check") || !hosts.length);
  if(!active&&!cached&&chosen==="current"&&currentAgent?.status!=="detected"){start.disabled=true;start.textContent="等待识别当前 Agent";}
  start.addEventListener("click", () => requestAgentCheck(candidateId, select.value));
  append(controls, label, select, start);
  const modelLink=element("a","text-link","查看 / 修改模型与思考强度 ↗");modelLink.href="#agents";modelLink.addEventListener("click",()=>$("candidate-dialog").close());controls.append(modelLink);
  if(!active&&cached){const other=element("details","check-history");other.dataset.key=`other-host-${job.id}`;append(other,element("summary","","更换检查 Agent"),controls);panel.append(other);}
  else if(!active)panel.append(controls);
  if(!job)panel.append(element("p", "quiet-note", "四种 Agent 共用检查任务与报告。只在你发起时调用模型；同一项目与条件24小时内复用结果。"));
  if (!job) { panel.append(element("p", "quiet-note", "Codex / Claude Code 可通过本机 CLI 检查；pi / DeepSeek Harness 可通过已接通宿主领取并回传。不可用或未登录时会说明原因。")); return; }
  const status = element("div", "agent-check-status"); status.setAttribute("role", "status");
  append(status, badge(job.current ? checkStatusLabels[job.status] || job.status : "条件变化，旧报告仅供参考", job.status === "failed" || !job.current ? "warning" : "teal"),
    element("span", "quiet-note", `${checkHostLabels[job.host || job.requested_host] || "Agent"} · ${date(job.updated_at, true)}`));
  panel.append(status, checkProgressView(job));
  panel.append(element("p","quiet-note",runtimeDescription(job)));
  updateCheckClocks();
  const preparation=array(app.state.preparation_plans).find(p=>p.candidate_id===candidateId);
  if(preparation){const button=element("button","button secondary",job.status==="completed"?"查看准备方案":"查看已有准备方案");button.type="button";button.id="check-open-plan";button.addEventListener("click",()=>openPreparation(preparation.id));panel.append(button);}
  if(job.fact_sync)panel.append(element("p","quiet-note",job.fact_sync.reason));
  if (active) {
    const cancel=element("button", "text-button", "取消检查");cancel.type="button";cancel.id="agent-check-cancel";
    cancel.addEventListener("click", () => cancelAgentCheck(job.id));panel.append(cancel);
    if(job.status === "queued") panel.append(element("p", "quiet-note", "自动调用会依次处理任务。选择“需宿主领取”的 Agent 后，要在该宿主中让它领取 Prospect 检查任务；网页不会冒充已经启动。"));
  }
  if (!job.report) return;
  const report=job.report;
  const verdict=job.recommendation?.label||{suitable:"可考虑尝试",unsuitable:"查看具体风险与限制",needs_info:"待进一步核验"}[report.verdict];
  append(panel, element("h4", "agent-verdict", verdict), element("p", "", job.recommendation?.reason||report.summary), element("p", "quiet-note", report.identity));
  if(job.recommendation)panel.append(auditView(job.recommendation));
  if(job.decision_note) panel.append(element("p", "quiet-note", job.decision_note));
  const details=element("details", "agent-report-details"); details.dataset.key=`agent-report-${job.id}`;
  details.append(element("summary", "", "查看七项检查与来源"));
  details.append(element("p","quiet-note",`原始报告：${report.summary}`));
  array(report.checks).forEach(check => {
    const section=element("section", "agent-finding");
    append(section, element("h4", "", `${checkTopicLabels[check.topic] || check.topic} · ${{pass:"已核验",fail:"不满足",unknown:"待确认"}[check.status] || check.status}`),element("p", "", check.finding));
    array(check.sources).forEach((url, index) => section.append(safeLink(url, `依据 ${index+1} ↗`, "text-link")));
    details.append(section);
  });
  array(report.sources).forEach(source => { const item=element("p", "agent-source");append(item,safeLink(source.url,source.title),element("span","quiet-note",source.note));details.append(item); });
  panel.append(details);
  for(const [key,title] of [["missing_information","仍需确认"],["next_steps","建议下一步"]]) {
    if(!array(report[key]).length) continue;
    panel.append(element("h4", "", title));const list=element("ul", "agent-next");array(report[key]).forEach(item=>list.append(element("li","",item)));panel.append(list);
  }
  panel.append(element("p", "quiet-note", job.usage ? `本次宿主回报：输入 ${number(job.usage.input_tokens)}${hasValue(job.usage.cached_input_tokens) ? `（缓存命中 ${number(job.usage.cached_input_tokens)}）` : ""} / 输出 ${number(job.usage.output_tokens)} tokens。用量不等于账单费用。` : "本次模型用量尚未回报，不计为零。"));
  panel.append(element("p", "quiet-note", "Agent 结论供你审阅，不构成收益保证或执行授权。下方原始线索保留供对照。"));
}
async function requestAgentCheck(candidateId, host) {
  if(app.pending.has("agent-check")) return;
  app.pending.add("agent-check");renderAgentCheck(candidateId);
  try {
    const result=await request("/api/checks/request", {candidate_id:candidateId,host});app.mutationRevision+=1;
    app.focusedCheckId=result.id;app.state.agent_checks=[result,...array(app.state.agent_checks).filter(j=>j.id!==result.id)];
    renderAgentCheck(candidateId);renderCheckCenter();
    toast(result.reused ? "已复用这个项目的检查任务或报告。" : "已提交 Agent 检查，进度和报告会显示在这里。");
    await loadState();
  } catch(error) {toast(error.message,true);}
  finally {app.pending.delete("agent-check");if(app.selectedId===candidateId)renderAgentCheck(candidateId);}
}
async function cancelAgentCheck(id) {
  try {const result=await request("/api/checks/cancel",{id});app.mutationRevision+=1;app.state.agent_checks=array(app.state.agent_checks).map(j=>j.id===id?result:j);renderCheckCenter();if($("candidate-dialog").open)renderAgentCheck(app.selectedId);}
  catch(error) {toast(error.message,true);}
}
function simulationContent(result, key = "simulation") {
  const block = element("div", "simulation-result");
  const title = element("div", "simulation-title");
  append(title, element("h3", "", "流程预演"), badge("显式模拟 · 无实际执行", "teal"), badge(preflightLabel(result), result.status === "blocked" ? "warning" : "teal"));
  append(block, title, element("p", "", result.status === "blocked" ? "参与条件预检尚未通过。以下是模拟步骤，没有启动挖矿，也没有产生费用。" : "以下为模拟步骤，不代表安装、挖矿、提交或交付已经发生。"));
  block.append(element("p", "detail-subtitle", result.status === "simulated" ? "准备步骤已完成模拟。下一步查看项目的执行路线与具体运行范围。" : "下一步：根据下方原因补充个人档案，或让当前 Agent 核验项目资料。试运行需从准备方案单独启动。"));
  const steps = array(result.steps);
  if (steps.length) {
    const list = element("ol", "simulation-steps");
    steps.forEach((step, index) => {
      const data = typeof step === "string" ? { detail: step } : object(step);
      const li = element("li", "simulation-step");
      const header = element("h4", "", display(data.name || data.title, `步骤 ${index + 1}`));
      header.append(statusBadge(data.status || "mock"));
      append(li, header, element("p", "", display(data.detail || data.description, "未提供步骤说明")), rawDetails(data, `${key}-step-${index}`, "完整步骤字段"));
      list.append(li);
    }); block.append(list);
  } else block.append(element("p", "detail-subtitle", "服务未返回步骤，请核对完整记录。"));
  const rewards = object(result.rewards);
  block.append(element("p", "detail-subtitle", `奖励：未产生真实奖励${hasValue(rewards.unit) ? `；记录单位为 ${display(rewards.unit)}` : ""}。`));
  block.append(rawDetails(result, key, "查看完整模拟结果"));
  return block;
}
async function simulateCandidate(id) {
  if (app.pending.has("simulate")) return;
  app.pending.add("simulate");
  const button = $("simulate-button");
  if (button) { button.disabled = true; button.textContent = "正在检查条件…"; }
  const output = $("simulation-result");
  output?.replaceChildren(element("p", "quiet-note", "正在计算适配条件并生成模拟步骤…"));
  try {
    const result = await request("/api/simulate", { candidate_id: id });
    app.simulation = result;
    if (app.selectedId === id && $("simulation-result")) {
      $("simulation-result").replaceChildren(simulationContent(result, `simulation-${result.id || id}`));
      $("simulation-result").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
    }
    await loadState();
  } catch (error) {
    if (app.selectedId === id && $("simulation-result")) $("simulation-result").replaceChildren(element("div", "inline-error", error.message));
    toast(error.message, true);
  } finally {
    app.pending.delete("simulate");
    if (app.selectedId === id && $("simulate-button")) { $("simulate-button").disabled = false; $("simulate-button").textContent = "重新检查条件（不运行）"; }
  }
}
function preflightLabel(result) {
  if (result.status !== "blocked") return translated("status", result.status);
  return result.assessment?.status === "unknown" ? "待补资料" : result.assessment?.status === "incompatible" ? "条件不匹配" : "预检未通过";
}
function renderRuns() {
  const all = array(app.state.runs);
  const validation = all.filter((run) => run.origin === "validation");
  const showValidation = $("show-validation-runs").checked;
  const runs = all.filter((run) => showValidation || run.origin !== "validation");
  const scans = array(app.state.scans);
  setText("run-count", `${runs.length} 条预检记录`);
  setText("validation-runs-note", validation.length ? `另有 ${validation.length} 条开发验证记录${showValidation ? "，已显示并标注" : "默认收起"}。这些来自界面测试，没有启动挖矿。` : "预检只检查参与条件，不启动项目。缺少资料会标为“待补资料”。");
  if (!runs.length) $("run-list").replaceChildren(empty("还没有你的参与预检", "选择项目后可检查设备、时间、成本与资格要求。开发验证记录已单独归类。", { label: "查看项目线索", run: () => { location.hash = "opportunities"; } }));
  else {
    const fragment = document.createDocumentFragment();
    runs.forEach((run, index) => {
      const block = element("article", "record");
      const candidate = array(app.state.candidates).find((item) => item.id === run.candidate_id);
      const header = element("div", "record-heading");
      append(header, element("strong", "", display(candidate?.name || run.candidate_name || run.candidate_id, "项目预检")), badge(preflightLabel(run), run.status === "blocked" ? "warning" : "teal"));
      append(block, header, element("div", "record-meta", `${date(run.at || run.created_at)} · ${run.origin === "validation" ? "开发验证" : "条件预检"} · 没有启动挖矿`));
      const missing = array(run.assessment?.missing).map(field => translated("field", field));
      const reason = missing.length ? `待补充：${missing.join("、")}` : array(run.assessment?.reasons).join("；");
      if (reason) block.append(element("p", "record-reason", reason));
      const details = element("details", "raw-details"); details.dataset.key = `run-${run.id || index}`;
      append(details, element("summary", "", "查看预检依据与模拟步骤"), simulationContent(run, `run-detail-${run.id || index}`));
      block.append(details); fragment.append(block);
    });
    $("run-list").replaceChildren(fragment);
  }
  if (!scans.length) $("scan-list").replaceChildren(empty("还没有扫描记录", "准备好时，可以点击页首“扫描公开来源”。它只读取已配置的公开信息，结果会留在这里。"));
  else {
    const fragment = document.createDocumentFragment();
    scans.forEach((scan, index) => {
      const block = element("article", "record");
      const header = element("div", "record-heading");
      const timestamp = scan.at || scan.started_at || scan.checked_at || scan.created_at;
      append(header, element("strong", "", `公开来源扫描 · ${date(timestamp, true)}`), statusBadge(scan.status));
      append(block, header, element("div", "record-meta", display(scan.summary || scan.message, "本次采集的结果与错误保留在完整记录中。")), rawDetails(scan, `scan-${scan.id || index}`));
      fragment.append(block);
    }); $("scan-list").replaceChildren(fragment);
  }
}
function renderSources() {
  let monitor=$("monitoring-controls");
  if(!monitor){monitor=element("div","notice-strip");monitor.id="monitoring-controls";$("source-list").before(monitor);}
  const enabled=app.state.monitoring?.enabled===true;
  const toggle=element("button","button secondary",enabled?"暂停持续发现":"开启持续发现");toggle.type="button";toggle.id="monitoring-toggle";
  toggle.disabled=app.pending.has("monitoring");toggle.addEventListener("click",async()=>{
    if(app.pending.has("monitoring"))return;app.pending.add("monitoring");renderSources();
    try{await request("/api/monitoring",{enabled:!enabled});app.mutationRevision++;await loadState();toast(enabled?(app.state.observation?.status==="running"?"已关闭持续发现开关；七日观察仍在采集。":"已暂停持续发现。"):"已开启持续发现，按来源频率读取公开信息。");}
    catch(error){toast(error.message,true);}finally{app.pending.delete("monitoring");renderSources();}
  });
  monitor.replaceChildren(element("p","",enabled?"持续发现已开启 · 按来源频率检查，规则采集不调用模型。":app.state.observation?.status==="running"?"持续发现开关已关闭 · 七日观察仍在采集；要停止自动采集，请到总览暂停观察。":"持续发现已暂停 · 手动扫描仍然可用。"),toggle);
  const sources = array(app.state.sources);
  if (!sources.length) { $("source-list").replaceChildren(empty("尚未配置来源", "没有可采集的来源。请通过本地配置添加经过验证的公开来源。")); return; }
  const fragment = document.createDocumentFragment();
  sources.forEach((source, index) => {
    const row = element("article", "source-row");
    const information = element("div");
    const heading = element("div", "source-title");
    append(heading, element("strong", "", display(source.label || source.id, "未命名来源")), source.enabled ? statusBadge(source.status) : badge("已停用"));
    information.append(heading);
    if (source.url) information.append(safeLink(source.url, display(source.url), "source-link"));
    const meta = element("div", "record-meta");
    append(meta, element("span", "", `频率 ${finite(source.interval_seconds) ? `${number(source.interval_seconds / 60, 1)} 分钟` : "尚待确认"}`), element("span", "", `最近成功 ${date(source.last_success, true)}`), element("span", "", `最近检查 ${date(source.last_checked, true)}`));
    information.append(meta);
    if(source.note)information.append(element('p','quiet-note',source.note));
    if(source.migration_note)information.append(element('p','quiet-note',source.migration_note));
    if(finite(source.next_check_epoch))meta.append(element('span','',`下次检查 ${date(new Date(source.next_check_epoch*1000).toISOString(),true)}`));
    if (source.error) information.append(element("p", "source-error", '覆盖中断：此来源暂时无法读取，不代表没有新项目。 '+source.error));
    const toggle = element("button", "toggle"); toggle.type = "button"; toggle.id = `source-toggle-${index}`;
    toggle.setAttribute("role", "switch"); toggle.setAttribute("aria-checked", String(Boolean(source.enabled)));
    toggle.setAttribute("aria-label", `${display(source.label || source.id, "来源")}：${source.enabled ? "已启用，点击停用" : "已停用，点击启用"}`);
    toggle.disabled = app.pending.has(`source-${source.id}`);
    toggle.addEventListener("click", () => toggleSource(source));
    append(row, information, toggle); fragment.append(row);
  }); $("source-list").replaceChildren(fragment);
}
function renderEvents() {
  const events = array(app.state.events);
  if (!events.length) { $("event-list").replaceChildren(empty("尚无证据事件", "项目变化、观察状态与核对事件将保留在此。")); return; }
  const fragment = document.createDocumentFragment();
  events.forEach((event, index) => {
    const block = element("article", "record");
    const payload = object(event.payload);
    const heading = element("div", "record-heading");
    append(heading, element("strong", "", display(event.title || event.kind || event.type, "观察事件")), element("span", "date-cell", date(event.at || event.created_at || event.timestamp, true)));
    append(block, heading, element("p", "record-meta", display(event.message || payload.message || payload.summary || payload.candidate_id, "事件已记录，可展开核对全部字段。")), rawDetails(event, `event-${event.id || index}`));
    fragment.append(block);
  }); $("event-list").replaceChildren(fragment);
}
function renderSettings() {
  const hardware = object(app.state.hardware);
  const usage = object(app.state.usage);
  const preferences = object(app.state.preferences);
  $("runtime-preferences").replaceChildren(
    definitionRow("运行时机", preferences.resource_strategy === "idle_only" ? "仅在电脑空闲时运行" : display(preferences.resource_strategy, "尚未记录")),
    definitionRow("优先原则", preferences.priority === "do_not_disrupt" ? "不影响日常使用" : display(preferences.priority, "尚未记录")),
    definitionRow("常规选择", preferences.routine_choices === "use_recommended_defaults" ? "使用推荐默认值" : display(preferences.routine_choices, "尚未记录"))
  );
  setText("resource-enforcement", preferences.enforcement === "live_execution_not_implemented"
    ? "真实任务尚未启用，因此当前没有执行资源限额。这里记录的是后续参与计划采用的偏好。"
    : "资源策略的执行状态尚待验证。偏好记录不等于已开始运行任务。");
  if (!app.profileDirty) {
    const form = $("profile-form");
    const profile = object(app.state.profile);
    ["electricity_price", "daily_hours", "cpu_limit_pct", "max_daily_cost", "available_minutes"].forEach((name) => { form.elements[name].value = hasValue(profile[name]) ? profile[name] : ""; });
    form.elements.gpu_allowed.checked = profile.gpu_allowed === true;
    form.elements.skill_level.value = [...form.elements.skill_level.options].some((option) => option.value === profile.skill_level) ? profile.skill_level : "";
    app.profileInitialized = true;
  }
  $("hardware-details").replaceChildren(
    definitionRow("处理器", display(hardware.cpu_name, "尚未探测")), definitionRow("逻辑核心", number(hardware.cpu_logical)), definitionRow("内存", finite(hardware.ram_gb) ? `${number(hardware.ram_gb, 1)} GB` : "尚未探测"), definitionRow("空闲存储", finite(hardware.disk_free_gb) ? `${number(hardware.disk_free_gb, 1)} GB` : "尚未探测"), definitionRow("显存", finite(hardware.vram_gb) ? `${number(hardware.vram_gb, 1)} GB` : "尚未探测"), definitionRow("系统架构", `${display(hardware.os)} / ${display(hardware.arch)}`), definitionRow("温度", finite(hardware.temperature_c) ? `${number(hardware.temperature_c, 1)} °C` : "未接入传感器"), definitionRow("功率", finite(hardware.power_w) ? `${number(hardware.power_w, 1)} W` : "未接入传感器"), definitionRow("探测时间", date(hardware.checked_at))
  );
  const usageBlock = document.createDocumentFragment();
  [["后台模型调用", usage.background_model_calls], ["输入 tokens", usage.input_tokens], ["输出 tokens", usage.output_tokens], ["缓存 tokens", usage.cached_tokens], ["待研究项目", usage.research_pending]].forEach(([label, value]) => usageBlock.append(append(element("div", "usage-line"), element("span", "", label), element("strong", "", number(value)))));
  append(usageBlock, definitionRow("主动 Agent 检查会话", number(usage.agent_check_sessions || 0)), definitionRow("宿主回传检查报告", number(usage.agent_check_host_reports || 0)), definitionRow("检查已回报输入 / 输出 tokens", `${number(usage.agent_check_input_tokens || 0)} / ${number(usage.agent_check_output_tokens || 0)}`), definitionRow("尚未回报用量的会话", number(usage.agent_check_usage_unreported || 0)));
  usageBlock.append(element("p", "quiet-note", "规则巡检不调用模型。主动 Agent 检查使用所选宿主的模型用量；未回报的用量保持未知，token 汇总只含已回报部分，不等于账单费用。"));
  $("usage-details").replaceChildren(usageBlock);
  renderAgentBudget();
  renderHosts();
}
function renderAgentBudget(){
  const budget=app.state.agent_budget;if(!budget)return;
  let section=$("agent-budget-section");
  if(!section){section=element("section","budget-section");section.id="agent-budget-section";$("usage-details").after(section);}
  if(app.budgetDirty)return;
  const automatic=budget.automatic||budget;const manual=budget.manual;
  section.replaceChildren(element("h3","","后台自动检查预算"),element("p","quiet-note","手动点击检查与重试不受此预算限制。当前后台公开来源采集使用规则，不调用模型。"),element("p","quiet-note",`北京时间 ${budget.day} · 自动检查 ${automatic.used_checks} 次 · 已回报 ${number(automatic.measured_tokens)} tokens · 未回报预留 ${number(automatic.reserved_tokens)}`));
  if(manual)section.append(element("p","quiet-note",`今日手动检查 ${manual.used_checks} 次 · 已回报 ${number(manual.measured_tokens)} tokens · ${manual.unreported_checks} 次用量未回报。这里只记录用量，不设置每日上限。`));
  const form=element("form","form-grid");form.id="agent-budget-form";
  for(const [key,labelText,max] of [["daily_checks","自动检查每天最多次数",20],["daily_tokens","自动检查每日 token 预算",2000000],["reservation_tokens","自动检查未知用量预留",200000]]){
    const label=element("label","",labelText);const input=element("input");input.type="number";input.name=key;input.min="0";input.max=String(max);input.step="1";input.required=true;input.value=budget.policy[key];label.append(input);form.append(label);
  }
  const submit=element("button","button secondary","保存自动检查预算");submit.type="submit";submit.disabled=app.pending.has("budget");form.append(submit);form.addEventListener("input",()=>{app.budgetDirty=true;});
  form.addEventListener("submit",async(event)=>{
    event.preventDefault();if(app.pending.has("budget"))return;app.pending.add("budget");submit.disabled=true;
    const payload=Object.fromEntries(["daily_checks","daily_tokens","reservation_tokens"].map(k=>[k,Number(form.elements[k].value)]));
    try{await request("/api/budget",payload);app.mutationRevision++;app.budgetDirty=false;await loadState();toast("后台自动检查预算已保存。");}
    catch(error){toast(error.message,true);}finally{app.pending.delete("budget");submit.disabled=false;}
  });section.append(form,element("p","quiet-note",budget.note));
}
function renderHosts() {
  const compatibility = app.state.host_compatibility;
  let entries;
  if (Array.isArray(compatibility)) entries = compatibility.map((value, index) => [value.host || value.name || value.id || `Agent ${index + 1}`, value]);
  else entries = Object.entries(object(compatibility));
  if (!entries.length) { $("host-list").replaceChildren(element("p", "quiet-note", "尚未返回宿主兼容性报告；此处不推断任何接入已验证。")); return; }
  const grid = element("div", "host-grid");
  entries.forEach(([name, entry]) => {
    const data = typeof entry === "string" ? { status: entry } : object(entry);
    const block = element("article", "host-item");
    append(block, element("h3", "", name), statusBadge(data.status || data.verification || "unverified"), element("p", "", display(data.note || data.reason || data.description, "请以实际宿主验证结果为准。")), rawDetails(data, `host-${name}`, "接入详情"));
    grid.append(block);
  }); $("host-list").replaceChildren(grid);
}
const effortLabels={default:"由模型决定",minimal:"minimal · 最少",low:"low · 轻量",medium:"medium · 标准",high:"high · 深入",xhigh:"xhigh · 更深入",max:"max · 最高"};
function runtimeDescription(job) {
  const config=job.runtime_config;
  if(!config)return "模型与思考强度：历史任务未记录，不从当前设置倒推。";
  if(config.method==="host_tools")return "模型与思考强度由领取任务的宿主会话决定；尚未回报实际配置。";
  const actual=array(config.observed_models);
  return `请求模型：${config.requested_model||"CLI 默认（未固定型号）"} · 思考强度：${config.requested_effort||"模型默认"} · 实际型号回报：${actual.length?actual.join("、"):"尚未回报"}${config.cli_version?` · 运行端：${config.cli_version}${config.cli_source==="desktop"?"（桌面随附）":""}`:""}`;
}
function renderAgentModels() {
  const data=app.state.agent_settings;const container=$("agent-model-settings");if(!data||app.modelsDirty)return;
  container.replaceChildren();const form=element("form","agent-model-form");form.id="agent-model-form";
  const routing=element("div","model-routing");const defaultLabel=element("label","","默认检查 Agent");
    const defaultSelect=element("select");defaultSelect.name="default_host";defaultSelect.id="default-check-host";defaultSelect.setAttribute("aria-label","默认检查 Agent");
  for(const [value,label] of [["any","自动选择可用 CLI"],["codex","Codex"],["claude","Claude Code"],["deepseek_api","DeepSeek API（独立接口）"],["pi","pi（在宿主中领取）"],["deepseek","DeepSeek Harness（在宿主中领取）"]]){const option=element("option","",label);option.value=value;defaultSelect.append(option);}
  defaultSelect.value=data.policy.default_host;defaultLabel.append(defaultSelect);append(routing,defaultLabel,element("p","quiet-note","开始参与会优先识别当前 Agent，此默认值不会覆盖识别结果。需要临时改用其他宿主或 API，可在参与页展开“其他检查方式”。"));form.append(routing);
  const grid=element("div","model-grid");
  for(const host of ["codex","claude"]){
    const selected=data.policy.hosts[host];const defaults=data.host_defaults[host]||{};const capability=array(app.state.agent_check_hosts).find(h=>h.id===host);
    const card=element("section","panel model-card");const header=element("div","record-heading");append(header,element("h3","",checkHostLabels[host]),badge(capability?.dispatch==="native_cli"?"本机 CLI 可调用":"尚未检测到 CLI",capability?.dispatch==="native_cli"?"teal":""));card.append(header);
    const fields=element("div","model-fields");const modelLabel=element("label","",`${checkHostLabels[host]} 模型`);const model=element("input");model.name=`${host}_model`;model.id=`${host}-model`;model.value=selected.model;model.maxLength=160;model.placeholder="留空使用 CLI 默认";model.autocomplete="off";
    const list=element("datalist");list.id=`${host}-model-options`;model.setAttribute("list",list.id);const suggestions=array(data.catalog?.[host]).map(m=>m.id);if(defaults.model&&!suggestions.includes(defaults.model))suggestions.unshift(defaults.model);if(host==="claude")suggestions.push("sonnet","opus","haiku");[...new Set(suggestions)].forEach(id=>{const option=element("option");option.value=id;list.append(option);});modelLabel.append(model,list);
    const effortLabel=element("label","",`${checkHostLabels[host]} 思考强度`);const effort=element("select");effort.name=`${host}_effort`;effort.id=`${host}-effort`;effort.setAttribute("aria-label",`${checkHostLabels[host]} 思考强度`);
    const updateEfforts=(wanted)=>{const match=array(data.catalog?.[host]).find(m=>m.id===model.value.trim());const choices=match?.efforts?.length?["default",...match.efforts]:data.efforts[host];effort.replaceChildren();choices.forEach(value=>{const option=element("option","",effortLabels[value]||value);option.value=value;effort.append(option);});if(!choices.includes(wanted)){const invalid=element("option","",`${wanted} · 此模型未声明支持`);invalid.value=wanted;effort.append(invalid);}effort.value=wanted;};updateEfforts(selected.effort);model.addEventListener("input",()=>updateEfforts(effort.value));effortLabel.append(effort);append(fields,modelLabel,effortLabel);card.append(fields);
    card.append(element("p","quiet-note",`宿主偏好：${defaults.model||"型号未设置"} / ${defaults.effort||"强度未设置"}。这是参考值，不等于后台检查当前配置。`));
    if(defaults.model||data.efforts[host].includes(defaults.effort)){const copy=element("button","text-button","填入宿主偏好");copy.type="button";copy.id=`use-${host}-defaults`;copy.addEventListener("click",()=>{if(defaults.model)model.value=defaults.model;updateEfforts(data.efforts[host].includes(defaults.effort)?defaults.effort:effort.value);app.modelsDirty=true;setText("model-save-message","已填入，保存后用于新检查。");});card.append(copy);}
    card.append(element("p","quiet-note",host==="codex"?"型号来自本机目录，也可填写模型 ID。后台使用独立只读配置，不会自动继承聊天的模型与强度。":"模型 ID 或 sonnet / opus / haiku 别名均可填写。别名的实际型号以任务回报为准。"));grid.append(card);
  }
  form.append(grid);
  const footer=element("div","model-save-bar");const save=element("button","button primary","保存模型设置");save.type="submit";save.id="save-agent-models";const message=element("span","form-message","保存不会启动检查，也不会改变正在运行的任务。");message.id="model-save-message";message.setAttribute("role","status");append(footer,save,message);form.append(footer);
  form.addEventListener("input",()=>{app.modelsDirty=true;message.textContent="有未保存的修改";});
  form.addEventListener("submit",async event=>{event.preventDefault();if(app.pending.has("models"))return;app.pending.add("models");save.disabled=true;save.textContent="正在保存…";
    const payload={default_host:defaultSelect.value,hosts:Object.fromEntries(["codex","claude"].map(h=>[h,{model:form.elements[`${h}_model`].value.trim(),effort:form.elements[`${h}_effort`].value}]))};
    try{const result=await request("/api/agent-settings",payload);app.mutationRevision++;app.modelsDirty=false;app.state.agent_settings=result;app.renderSignatures.agentSettings=JSON.stringify(result);renderAgentModels();setText("model-save-message","已保存，新发起的检查将使用这份配置。");toast("模型设置已保存。");}
    catch(error){message.textContent=error.message;toast(error.message,true);}finally{app.pending.delete("models");save.disabled=false;save.textContent="保存模型设置";}
  });container.append(form);
  const external=element("section","panel external-agents");append(external,element("h3","","由宿主会话管理的 Agent"),element("p","quiet-note",data.host_session_note));
  for(const [host,label] of [["pi","pi"],["deepseek","DeepSeek Harness"]]){const defaults=data.host_defaults[host]||{};append(external,definitionRow(label,`${defaults.model||"未读取到实际型号"} · ${defaults.effort||"思考强度未回报"}`));}
  external.append(element("p","quiet-note","这两端请在对应宿主选择模型后领取任务。读取到的本地偏好也不能证明当前会话正在使用它。"));container.append(external);
}
function renderDeepSeek() {
  const data=app.state?.agent_settings?.deepseek_api;if(!data||app.deepseekDirty)return;
  const box=$('deepseek-api-settings');box.replaceChildren();
  const header=element('div','record-heading');append(header,element('h2','','DeepSeek API'),badge(data.key_configured?(data.enabled?'已启用':'密钥已保存 · 未启用'):'待填写密钥',data.enabled?'teal':''));box.append(header);
  box.append(element('p','section-copy','直接连接 DeepSeek 或兼容接口。此入口独立于 DeepSeek Harness，可用于新发起的项目检查。'));
  const form=element('form','agent-model-form');form.id='deepseek-api-form';
  const grid=element('div','model-grid');
  function field(id,title,type,value){const label=element('label','',title);const input=element('input');input.id=id;input.type=type;input.value=value;input.autocomplete=type==='password'?'new-password':'off';label.append(input);grid.append(label);return input;}
  const url=field('deepseek-base-url','接口地址 · Base URL','url',data.base_url);url.required=true;url.placeholder='https://api.deepseek.com';
  const key=field('deepseek-api-key','API Key · 本机加密保存','password','');key.placeholder=data.key_configured?'留空保留已保存密钥':'填写该接口的 API Key';key.maxLength=512;
  const model=field('deepseek-model','模型 ID','text',data.model);model.required=true;model.setAttribute('list','deepseek-model-options');
  const list=element('datalist');list.id='deepseek-model-options';[...new Set(['deepseek-flash','deepseek-v4-pro',...array(data.models)])].forEach(id=>{const option=element('option');option.value=id;list.append(option);});model.after(list);
  const effortLabel=element('label','','思考强度');const effort=element('select');effort.id='deepseek-effort';effort.setAttribute('aria-label','DeepSeek 思考强度');for(const value of data.efforts){const option=element('option','',value==='off'?'关闭思考':effortLabels[value]||value);option.value=value;effort.append(option);}effort.value=data.effort;effortLabel.append(effort);grid.append(effortLabel);
  const limit=field('deepseek-max-tokens','单次输出上限 · tokens','number',data.max_tokens);limit.min=1024;limit.max=30000;limit.required=true;
  form.append(grid);
  const toggle=element('label','validation-toggle');const enabled=element('input');enabled.type='checkbox';enabled.id='deepseek-enabled';enabled.checked=data.enabled;append(toggle,enabled,document.createTextNode('启用 DeepSeek API 检查'));form.append(toggle);
  form.append(element('p','quiet-note','检查会向此接口发送项目资料和精简设备／偏好信息，并产生该接口的模型费用。使用本机读取的有限公开证据包，暂不具备自主搜索或完整代码审计能力。'));
  const actions=element('div','model-save-bar');const save=element('button','button primary','保存接口设置');save.type='submit';save.id='save-deepseek-api';const test=element('button','button secondary','测试连接并读取模型');test.type='button';test.id='test-deepseek-api';const remove=element('button','text-button','移除已保存密钥');remove.type='button';remove.id='remove-deepseek-key';remove.hidden=!data.key_configured;
  const message=element('p','form-message',app.deepseekMessage||'连接测试仅读取模型列表，不发起生成。密钥不会回显，也不会写入项目目录。');message.id='deepseek-api-message';message.setAttribute('role','status');append(actions,save,test,remove);form.append(actions,message);box.append(form);
  form.addEventListener('input',()=>{app.deepseekDirty=true;message.textContent='有未保存的接口设置';});
  const payload=()=>({enabled:enabled.checked,base_url:url.value.trim(),model:model.value.trim(),effort:effort.value,max_tokens:Number(limit.value),api_key:key.value});
  async function action(kind){
    if(app.pending.has('deepseek-api'))return;
    if(kind==='test'&&app.deepseekDirty){message.textContent='请先保存修改，再测试此配置。';return;}
    app.pending.add('deepseek-api');[...form.elements].forEach(e=>e.disabled=true);message.textContent=kind==='test'?'正在验证连接并读取模型列表…':'正在保存…';
    try{
      const result=await request(kind==='test'?'/api/agent-settings/deepseek/test':'/api/agent-settings/deepseek',kind==='test'?{}:kind==='remove'?{...payload(),enabled:false,api_key:'',remove_key:true}:payload(),70000);
      if(kind!=='test'){key.value='';app.deepseekDirty=false;app.state.agent_settings.deepseek_api=result;}
      else app.state.agent_settings.deepseek_api.models=result.models;
      app.mutationRevision++;renderDeepSeek();
      app.deepseekMessage=kind==='test'?`连接成功，读取到 ${result.models.length} 个模型。${result.selected_model_available?'当前模型在列表中。':'当前模型未在列表中，请核对模型 ID。'}`:kind==='remove'?'密钥已移除，接口已停用。':'已保存。在开始参与页展开“其他检查方式”，可选择 DeepSeek API。';setText('deepseek-api-message',app.deepseekMessage);
      await loadState();
    }catch(error){message.textContent=error.message;message.className='form-message inline-error';}
    finally{app.pending.delete('deepseek-api');[...form.elements].forEach(e=>e.disabled=false);}
  }
  form.addEventListener('submit',event=>{event.preventDefault();action('save');});test.addEventListener('click',()=>action('test'));remove.addEventListener('click',()=>action('remove'));
}
function renderModelHistory() {
  const container=$("agent-model-history");const jobs=array(app.state?.agent_checks).slice(0,8);const signature=JSON.stringify(jobs.map(j=>[j.id,j.status,j.runtime_config]));if(container.dataset.state===signature)return;container.dataset.state=signature;
  container.replaceChildren(...(jobs.length?jobs.map(job=>{const row=element("article","model-history-row");append(row,element("strong","",job.candidate_name),element("span","quiet-note",`${checkHostLabels[job.host||job.requested_host]||"等待领取"} · ${checkStatusLabels[job.status]||job.status}`),element("p","",runtimeDescription(job)));return row;}):[empty("还没有检查记录","新任务会记录发起时的模型配置和宿主实际回报。") ]));
}
async function scan() {
  if (app.pending.has("scan") || !app.state) return;
  app.pending.add("scan"); $("scan-button").disabled = true; $("scan-button").textContent = "正在核对可参与项目…";
  try {
    const result = await request("/api/scan", {}, 90000);
    const status = result.status;
    const message = result.economic_discovery ? result.message : finite(result.errors) && result.errors > 0 ? `扫描完成，${number(result.errors)} 个来源采集失败，请查看来源与证据。` : status === "throttled" || status === "skipped" || (result.checked === 0 && result.skipped > 0) ? display(result.message, "来源仍在冷却期，请稍后查看扫描记录。") : result.checked === 0 ? "没有需要采集的来源，请检查来源开关与采集频率。" : "扫描请求已完成，结果已记录在运行记录中。";
    toast(message, status === "error" || status === "failed" || result.errors > 0);
    await loadState();
  } catch (error) { toast(error.message, true); }
  finally { app.pending.delete("scan"); $("scan-button").textContent = "↻ 核对可参与项目"; renderConnection(); }
}
async function toggleSource(source) {
  const key = `source-${source.id}`;
  if (app.pending.has(key)) return;
  app.pending.add(key); renderSources();
  try {
    await request("/api/sources", { id: source.id, enabled: !source.enabled });
    toast(`${display(source.label || source.id, "来源")}已${source.enabled ? "停用" : "启用"}。`);
    await loadState();
  } catch (error) { toast(error.message, true); }
  finally { app.pending.delete(key); if (app.state) renderSources(); }
}
async function setObservation(action) {
  if (app.pending.has("observation")) return;
  app.pending.add("observation"); renderObservation();
  try {
    await request("/api/observation", { action });
    toast(action === "pause" ? "观察已暂停。" : action === "resume" ? "观察已继续，仅监测公开来源。" : "七日观察已开始，仅监测公开来源。规则不会启动挖矿。");
    await loadState();
  } catch (error) { toast(error.message, true); }
  finally { app.pending.delete("observation"); if (app.state) renderObservation(); }
}
async function saveProfile(event) {
  event.preventDefault();
  if (app.pending.has("profile")) return;
  const form = $("profile-form");
  if (!form.reportValidity()) return;
  const payload = {};
  ["electricity_price", "daily_hours", "cpu_limit_pct", "max_daily_cost", "available_minutes"].forEach((name) => { if (form.elements[name].value.trim() !== "") payload[name] = Number(form.elements[name].value); });
  if (form.elements.skill_level.value) payload.skill_level = form.elements.skill_level.value;
  payload.gpu_allowed = form.elements.gpu_allowed.checked;
  app.pending.add("profile"); renderConnection();
  $("save-profile-button").textContent = "正在保存…"; setText("profile-message", "");
  try {
    await request("/api/profile", payload);
    app.profileDirty = false;
    $("profile-message").className = "form-message"; setText("profile-message", "偏好已保存，适配结果将更新。");
    await loadState();
  } catch (error) { $("profile-message").className = "form-message error"; setText("profile-message", error.message); }
  finally { app.pending.delete("profile"); $("save-profile-button").textContent = "保存偏好"; renderConnection(); }
}
function navigate() {
  const requested = location.hash.replace(/^#/, "");
  const view = Object.hasOwn(views, requested) ? requested : "overview";
  const firstView = app.activeView === undefined;
  const viewChanged = !firstView && app.activeView !== view;
  app.activeView = view;
  document.querySelector('.page-heading').classList.toggle('compact-start-heading',view==='requests');
  document.querySelector('.page-heading').classList.toggle('lead-page-heading',view==='opportunities');
  $("scan-button").hidden = !["overview","opportunities","evidence","todo"].includes(view);
  $("start-project-global").hidden = view === "requests";
  const [title, eyebrow, description] = views[view];
  Object.keys(views).forEach((name) => { $(`view-${name}`).hidden = name !== view; });
  document.querySelectorAll("[data-view]").forEach((link) => { if (link.dataset.view === view) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current"); });
  setText("breadcrumb", title); setText("page-title", title); setText("page-eyebrow", eyebrow); setText("page-description", description);
  document.title = `${title} · Prospect`;
  if(app.state)renderCheckCenter();
  if (viewChanged) window.scrollTo(0, 0);
  if (firstView || viewChanged) animateEntrance("page", [document.querySelector(".page-heading"), ...$(`view-${view}`).children]);
}

$("guide-start").addEventListener("click", () => openGuide());
$("guide-launch").addEventListener("click", () => openGuide());
$("guide-skip").addEventListener("click", () => {
  guide.status = "skipped";
  guide.open = false;
  saveGuideState();
  renderGuideEntry();
  $("guide-launch").focus({ preventScroll: true });
  toast("可以先自己看看。需要时，从右上角打开“使用指南”。");
});
$("guide-close").addEventListener("click", () => closeGuide());
$("guide-dialog").addEventListener("cancel", rememberGuideClosed);
$("guide-dialog").addEventListener("close", () => {
  rememberGuideClosed();
  if (document.querySelector("dialog[open]")) return;
  const trigger = guide.returnFocus;
  const target = trigger?.isConnected && trigger.tabIndex >= 0 && trigger.getClientRects().length && !trigger.closest("[hidden]") && !trigger.closest("dialog") ? trigger : $("guide-launch");
  target.focus({ preventScroll: true });
});
$("guide-prev").addEventListener("click", () => moveGuide(-1));
$("guide-next").addEventListener("click", () => {
  if (guide.status === "completed") { closeGuide("done"); return; }
  if (guide.step < guideSteps.length - 1) { moveGuide(1); return; }
  guide.status = "completed";
  saveGuideState();
  renderGuide();
  $("guide-title").focus({ preventScroll: true });
});
$("guide-page").addEventListener("click", () => {
  const route = guide.status === "completed" ? "opportunities" : guideSteps[guide.step].route;
  closeGuide("navigate");
  location.hash = route;
});
$("show-validation-runs").addEventListener("change", () => { if (app.state) renderRuns(); });
$("close-participation").addEventListener("click", () => $("participation-dialog").close());
$("refresh-button").addEventListener("click", () => loadState());
$("retry-button").addEventListener("click", () => loadState());
$("scan-button").addEventListener("click", scan);
$("candidate-search").addEventListener("input", ()=>typeof filterLeads==='function'&&filterLeads());
$("category-filter").addEventListener("change", ()=>typeof filterLeads==='function'&&filterLeads());
$("participation-filter").addEventListener("change", ()=>typeof filterLeads==='function'&&filterLeads());
$('compute-filter').addEventListener('change',()=>typeof filterLeads==='function'&&filterLeads());
$("profile-form").addEventListener("input", () => { app.profileDirty = true; setText("profile-message", "有未保存的修改"); $("profile-message").className = "form-message"; });
$("profile-form").addEventListener("submit", saveProfile);
$("close-detail").addEventListener("click", () => $("candidate-dialog").close());
$("candidate-dialog").addEventListener("click", (event) => { if (event.target === $("candidate-dialog")) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
$("observation-button").addEventListener("click", () => {
  if (!app.state) return;
  if (app.observationAction === "pause") { setObservation("pause"); return; }
  setText("confirm-title", app.observationAction === "resume" ? "继续七日观察？" : "开始持续观察？");
  setText("confirm-description", app.observationAction === "resume" ? "本地服务将恢复读取已启用的公开来源，继续累计这次七日观察的真实时长与覆盖率，已有记录会保留。" : "本地服务将在接下来 7 天按配置频率读取已启用的公开来源，累计真实时长与覆盖率。");
  setText("confirm-observation", app.observationAction === "resume" ? "继续观察" : "开始观察");
  $("observation-dialog").returnValue = "cancel";
  openExclusiveDialog("observation-dialog");
});
$("observation-dialog").addEventListener("close", () => { if ($("observation-dialog").returnValue === "confirm") setObservation(app.observationAction); });
window.addEventListener("hashchange", navigate);
window.addEventListener("online", () => loadState());
document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - app.lastSuccess > 15000) loadState(); });
navigate();
renderGuideEntry();
if (guide.open) openGuide({ restore: true });
loadState({ initial: true });
setInterval(() => { renderConnection(); if (!document.hidden) loadState(); }, 15000);
setInterval(() => {if(!document.hidden)loadChecks();},2000);
setInterval(() => {if(!document.hidden)updateCheckClocks();},1000);
