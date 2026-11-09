"use strict";

const leadExplorer={data:null,offset:0,limit:20,sequence:0,pending:"",signature:null,timer:null};
function leadCandidate(id){
  return [...array(leadExplorer.data?.items),...array(app.state?.lead_catalog?.items),...array(app.state?.candidates),...array(app.state?.discovery_archive)].find(item=>item.id===id);
}
function leadQuery(){
  return new URLSearchParams({offset:leadExplorer.offset,limit:leadExplorer.limit,q:$("candidate-search").value.trim(),
    category:$("category-filter").value,compute:$("compute-filter").value,stage:$("participation-filter").value}).toString();
}
function renderLeadExplorer(){
  if(!app.state||app.activeView!=="opportunities")return;
  loadLeadPage();
}
function filterLeads(){
  leadExplorer.offset=0;clearTimeout(leadExplorer.timer);
  leadExplorer.timer=setTimeout(()=>loadLeadPage(),160);
}
async function loadLeadPage(){
  if(!app.state||app.activeView!=="opportunities")return;
  const query=leadQuery();if(leadExplorer.pending===query)return;
  const sequence=++leadExplorer.sequence;leadExplorer.pending=query;
  $("candidate-list").setAttribute("aria-busy","true");setText("lead-loading",leadExplorer.data?"正在更新线索…":"正在读取全部线索…");
  try{
    const result=await request("/api/leads?"+query);
    if(sequence!==leadExplorer.sequence||query!==leadQuery())return;
    if(!Array.isArray(result.items)||!Number.isInteger(result.total))throw new Error("线索数据暂时不完整，请重试。");
    if(result.matched&&leadExplorer.offset>=result.matched){leadExplorer.offset=Math.floor((result.matched-1)/leadExplorer.limit)*leadExplorer.limit;leadExplorer.pending="";loadLeadPage();return;}
    leadExplorer.data=result;$("lead-error").hidden=true;renderLeadPage(result);
  }catch(error){
    if(sequence!==leadExplorer.sequence||query!==leadQuery())return;
    $("lead-error").hidden=false;setText("lead-error-message",`${leadExplorer.data?"保留上次结果。":""}${error.message}`);
  }finally{
    if(sequence===leadExplorer.sequence){leadExplorer.pending="";$("candidate-list").setAttribute("aria-busy","false");setText("lead-loading","");}
  }
}
function leadTable(items){
  const table=element("table","data-table lead-table");table.setAttribute("aria-label","全部项目线索与保留依据");
  const head=element("thead"),heading=element("tr");
  for(const [title,cls] of [["项目 / 设备方向","lead-project"],["发现阶段","lead-stage"],["为什么保留 / 排除","lead-reason"],["下一步","lead-action"]]){
    const cell=element("th",cls,title);cell.scope="col";heading.append(cell);
  }
  head.append(heading);const body=element("tbody");
  for(const item of items){
    const info=item.lead_info, row=element("tr"),project=element("td","lead-project");
    const name=element("button","project-name-button",item.name);name.type="button";name.id="lead-name-"+item.id;
    name.addEventListener("click",()=>openCandidate(item.id));
    const meta=element("div","lead-meta");meta.append(badge(item.compute_profile.label),element("span","",translated("category",item.category)));
    project.append(name,meta,element("p","lead-summary",item.summary||"尚无公开简介"));
    const stage=element("td","lead-stage");stage.append(badge(info.stage_label,info.stage==="upcoming"?"teal":""));
    if(info.important)stage.append(element("span","lead-important","☆ 重点待办"));
    const reason=element("td","lead-reason");reason.append(element("p","",info.reason));
    reason.append(element("p","lead-review",info.review_status==="completed"?`有 Agent 报告 · ${date(info.reviewed_at)}${info.project_matches_report?"":" · 资料需复核"}`:"尚无完成的 Agent 报告"));
    const action=element("td","lead-action"),button=element("button","button secondary","查看 / 检查");button.type="button";
    button.id="lead-open-"+item.id;button.setAttribute("aria-label","查看与检查："+item.name);button.addEventListener("click",()=>openCandidate(item.id));action.append(button);
    if(info.todo_id){const link=element("a","text-link","跟进待办 ↗");link.href="#todo";action.append(link);}
    row.append(project,stage,reason,action);body.append(row);
  }
  table.append(head,body);return table;
}
function renderLeadPage(data){
  setText("results-count",data.matched?`显示 ${data.offset+1}–${data.offset+data.items.length} / ${data.matched} 条匹配线索`:`没有匹配线索 · 共保留 ${data.total} 条`);
  setText("lead-total",`全部 ${data.total} 条`);setText("lead-priority",`☆ ${data.important_count} 个重点待办`);
  setText("lead-summary",`待核实 ${data.counts.unverified} · 待开挖 ${data.counts.upcoming} · 已开放 ${data.counts.open} · 有依据排除 ${data.counts.excluded} · 有完成报告 ${data.reviewed_count}`);
  const signature=JSON.stringify([data.filters,data.offset,data.matched,data.total,data.items.map(item=>[item.id,item.name,item.summary,item.lead_info,item.compute_profile])]);
  if(signature===leadExplorer.signature)return;leadExplorer.signature=signature;
  const focused=document.activeElement?.id;
  $("candidate-list").replaceChildren(data.items.length?leadTable(data.items):empty("没有匹配的线索","换个关键词或筛选条件试试。未核实的项目仍保存在“待核实”中。",{label:"清除筛选",run:clearLeadFilters}));
  const pager=$("lead-pagination");pager.replaceChildren();pager.hidden=data.matched<=leadExplorer.limit;
  for(const [id,label,disabled,offset] of [["lead-prev","上一页",data.offset===0,Math.max(0,data.offset-leadExplorer.limit)],["lead-next","下一页",data.next_offset===null,data.next_offset]]){
    const button=element("button","button secondary",label);button.type="button";button.id=id;button.disabled=disabled;
    button.addEventListener("click",()=>{leadExplorer.offset=offset;loadLeadPage();});pager.append(button);
  }
  if(focused&&document.activeElement===document.body)$(focused)?.focus({preventScroll:true});
}
function clearLeadFilters(){
  $("candidate-search").value="";for(const id of ["category-filter","compute-filter","participation-filter"])$(id).value="all";
  leadExplorer.offset=0;loadLeadPage();$("candidate-search").focus();
}
$("lead-retry").addEventListener("click",()=>loadLeadPage());
$("lead-clear").addEventListener("click",clearLeadFilters);
window.addEventListener("hashchange",()=>{if(app.activeView==="opportunities")renderLeadExplorer();});
if(app.activeView==="opportunities")renderLeadExplorer();
