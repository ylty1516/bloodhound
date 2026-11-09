"use strict";
const launchUi={signature:null,filter:"active",busy:false};
function watchNode(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function watchTime(value){if(!value)return "开挖时间待公布";const d=new Date(value);return Number.isNaN(d.valueOf())?"时间待核对":new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(d)+" 北京时间";}
function watchPhase(item){return ({not_started:"主网待开挖",unknown:"开挖消息待核实",due:"公告时间已到 · 待核对开放",open:"已开放挖矿",cancelled:"已取消",retracted:"预告已撤回",needs_recheck:"公告需要重新核对"})[item.phase]||"待核对";}
function watchEntry(container,items){
  if(!container)return;container.hidden=false;
  const link=watchNode("a",undefined,"watch-entry-link");link.href="#todo";
  const copy=watchNode("div");copy.append(watchNode("strong",items.length?`☆ ${items.length} 个重点开挖待办`:"☆ 关注下一次开挖"));
  copy.append(watchNode("p",items.length?`${items[0].name} · ${watchTime(items[0].starts_at)}`:"已公布挖掘消息、尚未开挖；CPU 优先，GPU 其次。"));
  link.append(copy,watchNode("span","查看待办 →","watch-entry-action"));container.replaceChildren(link);
}
function renderLaunchWatch(){
  const state=app.state?.launch_watch;if(!state)return;
  const items=array(state.items),important=items.filter(x=>x.critical);
  setText("nav-watch-count",important.length||"");
  const signature=JSON.stringify([items.map(({starts_in_seconds,...item})=>item),launchUi.filter,launchUi.busy]);
  if(launchUi.signature!==signature){
    launchUi.signature=signature;
    watchEntry($("watch-overview"),important);watchEntry($("watch-start"),important);
    const visible=items.filter(x=>launchUi.filter==="all"||(launchUi.filter==="done"?["done","dismissed"].includes(x.todo_status):["pending","watching"].includes(x.todo_status)));
    const list=$("watch-list");
    if(!visible.length){const box=watchNode("div",undefined,"watch-empty");box.append(watchNode("h2",launchUi.filter==="active"?"正在守候下一份开挖公告":"这里还没有已处理记录"),watchNode("p","公告命中后会自动加入重点待办。钱包、交易与安全审阅状态会分别说明。"));list.replaceChildren(box);}
    else list.replaceChildren(...visible.map(item=>{
      const row=watchNode("article",undefined,`watch-row ${item.critical?"is-important":""}`);row.dataset.id=item.id;
      const body=watchNode("div",undefined,"watch-row-body"),tags=watchNode("div",undefined,"watch-tags");
      if(item.critical)tags.append(watchNode("span","重点关注","watch-important"));
      tags.append(watchNode("span",({cpu:"CPU 优先",gpu:"GPU 其次",either:"CPU / GPU · CPU 优先",unknown:"设备待核实",asic:"ASIC 方向"})[item.compute],"badge"));
      tags.append(watchNode("span",item.evidence_kind==="primary"?"一手公告":"线索 · 身份待核实","watch-quiet"));
      body.append(tags,watchNode("h2",item.name),watchNode("p",`${watchPhase(item)} · ${watchTime(item.starts_at)}`,"watch-date"));
      body.append(watchNode("p",item.evidence_note,"watch-note"));
      const wallet=({binance:"币安钱包兼容",native:"项目原生钱包",unknown:"钱包兼容性待核实"})[item.wallet];
      body.append(watchNode("p",`${wallet} · 交易与经济价值单独核验 · 加入待办不启动挖矿`,"watch-quiet"));
      const actions=watchNode("div",undefined,"watch-actions");
      const proof=watchNode("a","查看公告 ↗","text-link");proof.href=item.evidence_url;proof.target="_blank";proof.rel="noopener noreferrer";actions.append(proof);
      if(item.critical){
        const check=watchNode("button","让当前 Agent 核对","button secondary");check.type="button";check.onclick=()=>{openCandidate(item.candidate_id);requestAgentCheck(item.candidate_id,"current");};actions.append(check);
      }
      const decision=(label,status)=>{const b=watchNode("button",label,"text-button");b.type="button";b.disabled=launchUi.busy;b.onclick=()=>watchDecide(item.id,status);return b;};
      if(item.todo_status==="pending")actions.append(decision("设为跟进","watching"));
      if(["pending","watching"].includes(item.todo_status))actions.append(decision(item.todo_status==="watching"?"跟进中 · 标为完成":"标为完成","done"));
      else actions.append(decision("恢复待办","pending"));
      row.append(body,actions);return row;
    }));
  }
  renderWatchScan();
}
function renderWatchScan(){
  const state=app.state?.launch_watch;if(!state)return;
  const scan=state.scan||{},active=["running","queued"].includes(scan.status);
  $("watch-scan").disabled=active||launchUi.busy;
  if(active){const seconds=Math.max(0,Math.floor((Date.now()-Date.parse(scan.started_at))/1000));setText("watch-scan-state",`正在读取公开公告 · 已用 ${seconds} 秒 · 发现后自动加入重点待办`);}
  else if(scan.result)setText("watch-scan-state",`最近检查 ${scan.result.checked} 个来源${scan.result.errors?` · ${scan.result.errors} 个暂时不可用`:""} · CPU 优先，GPU 其次`);
  else{const unavailable=array(app.state.sources).filter(s=>s.enabled&&s.status==="error").length;setText("watch-scan-state",`公告巡检${app.state.monitoring?.enabled?"已开启":"已暂停"}${unavailable?` · ${unavailable} 个来源暂时不可用`:""} · 常规 15–30 分钟 · 不调用模型`);}
}
async function watchDecide(id,status){
  if(launchUi.busy)return;launchUi.busy=true;renderLaunchWatch();
  try{await request("/api/launch-watch/decision",{id,status});app.mutationRevision+=1;await loadState();}
  catch(error){toast(error.message,true);}finally{launchUi.busy=false;renderLaunchWatch();}
}
$("watch-filter").addEventListener("change",()=>{launchUi.filter=$("watch-filter").value;renderLaunchWatch();});
$("watch-scan").addEventListener("click",async()=>{
  if(launchUi.busy)return;launchUi.busy=true;renderLaunchWatch();
  try{await request("/api/scan",{});app.mutationRevision+=1;await loadState();}
  catch(error){toast(error.message,true);}finally{launchUi.busy=false;renderLaunchWatch();}
});
setInterval(()=>{if(app.activeView==="todo")renderWatchScan();},1000);
