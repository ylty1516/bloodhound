"use strict";

// One place to choose a project, follow its check, and open a bounded run.
const participationStart = {candidate:null, host:'current', signature:'', error:''};
try{const saved=JSON.parse(sessionStorage.getItem('prospect_participation_selection_v2')||'null');if(saved){participationStart.candidate=saved.candidate;participationStart.host=saved.host||'current';}else participationStart.candidate=JSON.parse(sessionStorage.getItem('prospect_participation_selection')||'null')?.candidate||null;}catch{}
function rememberParticipation(){try{sessionStorage.setItem('prospect_participation_selection_v2',JSON.stringify({candidate:participationStart.candidate,host:participationStart.host}));}catch{}}

function participationAgent(state,choice='current',check=null){
  const context=state.agent_context||{};const automatic=choice==='current';
  const active=check&&['queued','running'].includes(check.status);
  const host=active?(check.host||check.requested_host):(automatic?(context.status==='detected'?context.host:null):choice);
  return {host,automatic,unresolved:automatic&&!host,label:!host?(context.status==='ambiguous'?'等待确认当前宿主':'等待 Agent 连接'):`${active?'本次检查':automatic?'已识别':'临时指定'} · ${checkHostLabels[host]||host}`};
}

function participationStep(state, candidateId, host='any', jobs=[]) {
  const candidate=array(state?.candidates).find(c=>c.id===candidateId);
  if(!candidate)return {phase:'choose',step:0,title:'先选一个想参与的项目',note:'选好后，先让 Agent 核验。检查过程中可以离开页面，再回来继续。',action:'choose',label:'选择一个项目'};
  const checkJobs=array(state.agent_checks).filter(j=>j.candidate_id===candidateId);
  const active=checkJobs.find(j=>['queued','running'].includes(j.status));
  const check=active||checkJobs.find(j=>['any','current'].includes(host)||j.host===host||j.requested_host===host);
  const plans=array(state.preparation_plans).filter(p=>p.candidate_id===candidateId);
  const plan=plans.find(p=>p.check_id===check?.id)||plans[0];
  const run=jobs.find(j=>j.mode!=='diagnostic'&&j.binding?.candidate_id===candidateId);
  const base={candidate,check,plan,run};
  if(run&&['queued','waiting_idle','preparing','running','stopping','verifying'].includes(run.status))return {...base,phase:'running',step:2,title:'项目正在运行',note:run.message,action:'run-progress',label:'查看运行进度'};
  if(active)return {...base,phase:'checking',step:1,title:active.status==='queued'?'已提交，等待 Agent 接手':'Agent 正在检查这个项目',note:active.progress||'阶段和最后活动会在下方更新。',action:'checking',label:'检查进行中…'};
  const launch=candidate.launch;
  if(launch){
    if(launch.status==='not_integrated'||launch.status==='needs_software'){
      const alternative=launch.status==='not_integrated'&&array(state.preparation_plans).some(p=>p.candidate_id!==candidateId&&array(p.execution_drivers).length);
      return {...base,phase:'not_integrated',step:0,title:'暂不能运行：启动功能还没接入',note:launch.reason,action:alternative?'routes':'details',label:alternative?'看看已接入的项目':'查看项目资料'};
    }
    if(['unsafe','closed'].includes(launch.status))return {...base,phase:'blocked',step:1,title:launch.label,note:launch.reason,action:plan?'plan':'details',label:'查看原因'};
    if(launch.can_configure&&plan)return {...base,phase:'configure',step:2,title:'可以设置运行',note:launch.reason,action:'configure',label:'设置并启动'};
    if(launch.status==='preparing')return {...base,phase:'prepare',step:1,title:'还不能运行：安全检查未完成',note:'启动流程已接好，还需要检查要下载的这个版本是否安全。',action:'check',label:check?.status==='failed'?'重新检查资料':'让 Agent 检查资料'};
  }
  if(check?.status==='failed'||check?.status==='cancelled')return {...base,phase:'retry',step:1,title:check.status==='failed'?'上次检查没有完成':'检查已停止',note:check.progress||'可以重新检查，也可以更换 Agent。',action:'check',label:'重新检查这个项目'};
  if(check && check.current===false)return {...base,phase:'stale',step:1,title:'项目资料有变化，需要重新检查',note:'旧报告仍可查看；新检查完成后再决定是否启动。',action:'check',label:'更新项目检查'};
  if(plan){
    const supported=array(plan.execution_drivers).length>0;
    const suggested=plan.recommendation?.status==='suggested_trial';
    return {...base,phase:supported&&suggested?'configure':'blocked',step:2,
      title:!supported?'这个项目还不能在这里启动':suggested?'下一步：确认本次运行范围':'下一步：补齐启动条件',
      note:!supported?'Agent 可以检查这个项目，但自动安装、启动和结果验证还没有接入。重复检查不会自动补上运行功能。':suggested?'选择运行方式和时长，核对范围后再点击启动。系统会再次核验实际启动条件。':plan.recommendation?.reason||'还没有针对这个版本的有效安全审阅，查看具体缺项后再继续。',
      action:supported?'configure':'plan',label:supported?(suggested?'设置并启动':'查看启动条件'):'查看检查结果'};
  }
  if(check?.status==='completed')return {...base,phase:'report',step:2,title:'检查报告已完成',note:'还没有可用的运行方案。先查看结论和待解决事项。',action:'report',label:'查看检查结果'};
  return {...base,phase:'check',step:1,title:'下一步：让 Agent 检查',note:'核验项目来源、参与要求和风险。此步会使用所选 Agent 的额度；不会安装或启动项目。',action:'check',label:'让 Agent 检查这个项目'};
}

function startParticipation(candidateId=null){
  if(!candidateId||array(app.state?.candidates).find(c=>c.id===candidateId)?.mining_route){location.hash='requests';if(candidateId&&typeof openEconomicMining==='function')openEconomicMining();return;}
  participationStart.candidate=candidateId;participationStart.error='';rememberParticipation();
  document.querySelectorAll('dialog[open]').forEach(d=>d.close());
  location.hash='requests';renderParticipationStart();
  $('participation-start-panel').scrollIntoView({block:'start',behavior:'auto'});
  $('start-project').focus({preventScroll:true});
}

async function startSelectedCheck(candidateId){
  if(app.pending.has('agent-check'))return;
  participationStart.error='';app.pending.add('agent-check');renderParticipationStart();
  try{
    const result=await request('/api/checks/request',{candidate_id:candidateId,host:participationStart.host});
    app.mutationRevision++;app.state.agent_checks=[result,...array(app.state.agent_checks).filter(j=>j.id!==result.id)];
    renderCheckCenter();await loadState();
  }catch(error){participationStart.error=error.message;}
  finally{app.pending.delete('agent-check');renderParticipationStart();}
}

function renderParticipationStart(){
  const state=app.state;if(!state||!$('start-project'))return;
  const select=$('start-project');const candidates=array(state.candidates);
  const integrated=candidates.filter(c=>c.launch&&c.launch.status!=='not_integrated'&&array(state.preparation_plans).some(p=>p.candidate_id===c.id&&array(p.execution_drivers).length));
  if(!participationStart.candidate){
    participationStart.candidate=array(state.agent_checks).find(j=>['queued','running'].includes(j.status))?.candidate_id||integrated[0]?.id||null;
  }
  const shown=candidates.filter(c=>integrated.some(p=>p.id===c.id)||c.id===participationStart.candidate);
  const visibleChoices=shown.length?shown:candidates;
  const choices=JSON.stringify(visibleChoices.map(c=>[c.id,c.name,c.launch?.label]));
  if(select.dataset.choices!==choices){
    select.dataset.choices=choices;
    const placeholder=element('option','','请选择项目');placeholder.value='';
    select.replaceChildren(placeholder,...visibleChoices.map(c=>{const o=element('option','',`${c.name}${c.launch?' · '+c.launch.label:''}`);o.value=c.id;return o;}));
  }
  select.value=participationStart.candidate||'';
  const hostSelect=$('start-agent');const hosts=array(state.agent_check_hosts);
  const context=state.agent_context||{};
  const hostSignature=JSON.stringify(hosts);
  if(hostSelect.dataset.choices!==hostSignature){
    hostSelect.dataset.choices=hostSignature;
    const automatic=element('option','','自动识别当前 Agent');automatic.value='current';
    hostSelect.replaceChildren(automatic,...hosts.map(h=>{const o=element('option','',`${h.label}${h.dispatch==='not_configured'?' · 需先配置':h.dispatch==='host_tools'?' · 需打开宿主':''}`);o.value=h.id;return o;}));
  }
  hostSelect.value=participationStart.host;
  const jobs=typeof execution!=='undefined'?array(execution.state?.jobs):array(state.executions?.jobs);
  const flow=participationStep(state,participationStart.candidate,participationStart.host,jobs);
  const {heartbeat_at,...stableCheck}=flow.check||{};
  const signature=JSON.stringify([flow.phase,flow.title,flow.note,flow.action,flow.candidate?.id,stableCheck,flow.plan,flow.run?.status,participationStart.host,context,state.agent_budget,hosts,app.pending.has('agent-check'),participationStart.error]);
  if(signature===participationStart.signature)return;participationStart.signature=signature;
  const selection=participationAgent(state,participationStart.host,flow.check);
  const {automatic,unresolved}=selection;const effective=selection.host;
  const capability=hosts.find(h=>h.id===effective);
  const unconfigured=effective==='deepseek_api'&&capability?.dispatch!=='provider_api';
  const manual=effective!=='any'&&capability && !['native_cli','provider_api','not_configured'].includes(capability.dispatch);
  hostSelect.disabled=flow.phase==='checking';
  setText('start-agent-detected',selection.label);
  $('start-agent-detected').dataset.state=unresolved?'waiting':automatic?'detected':'manual';
  setText('start-agent-note',unresolved?'从正在使用的 Agent 启动或调用 Prospect 后自动识别；也可以展开“其他检查方式”。':flow.phase==='checking'?`本次检查使用发起时的 ${checkHostLabels[effective]||effective}，识别结果变化只影响下次检查。`:unconfigured?'DeepSeek API 还未启用，请先填写并保存接口设置。':manual?'已识别当前宿主。这个 Agent 需要在已打开的宿主中领取任务，提交后会显示等待状态。':automatic?'根据最近与 Prospect 交互且仍在运行的 Agent 自动选择，使用该宿主已保存的模型设置。':'本次使用临时指定的检查方式；切回自动识别即可跟随当前 Agent。');
  $('start-agent-note').hidden=automatic&&!unresolved&&!manual&&flow.phase!=='checking';
  $('start-steps').replaceChildren(...['选择项目','Agent 检查','启动运行'].map((text,index)=>{
    const li=element('li',index<flow.step?'done':index===flow.step?'current':'');
    if(index===flow.step)li.setAttribute('aria-current','step');
    append(li,element('span','step-number',index<flow.step?'✓':String(index+1)),element('span','',text));return li;
  }));
  const status=$('start-status');status.replaceChildren();
  const compute=flow.candidate?.compute_profile;
  if(compute){const device=element('div','project-device');const chip=badge(compute.label,compute.basis==='discovery_hint'?'':'teal');chip.title=compute.reason;device.append(chip);status.append(device);}
  append(status,element('h3','',flow.title),element('p','',flow.note));
  if(flow.candidate?.launch?.owner&&flow.phase!=='checking')status.append(element('p','blocker-owner',flow.candidate.launch.owner==='software'?'由软件继续完善，无需你修改链上参数。':'由 Agent 继续核验，无需你判断代码或校验码。'));
  if(flow.candidate?.launch?.testnet)status.append(element('p','trial-explanation','测试网练习 · 测试币不能兑现'));
  if(flow.phase==='prepare'){
    const progress=element('div','preparation-progress');
    append(progress,element('span','done','✓ 已接入'),element('span','pending','○ 待安全检查'),element('span','','○ 待你确认'));status.append(progress);
  }
  if(flow.check&&flow.phase==='checking')status.append(checkProgressView(flow.check));
  if(flow.run&&flow.phase!=='running')status.append(element('p','quiet-note',`上次运行：${executionNames[flow.run.status]||flow.run.status}。再次启动需要重新确认范围。`));
  const actions=$('start-actions');actions.replaceChildren();
  let label=flow.label;let action=flow.action;let disabled=flow.phase==='checking'||app.pending.has('agent-check');
  if(action==='check'&&unresolved){disabled=true;label='等待识别当前 Agent';}
  else if(action==='check'&&unconfigured){action='settings';label='先配置 DeepSeek API';}
  if(app.pending.has('agent-check'))label='正在提交检查…';
  const button=element('button','button primary start-primary',label);button.id='start-next';button.type='button';button.disabled=disabled;
  button.addEventListener('click',async()=>{
    if(action==='choose'){select.focus();if(typeof select.showPicker==='function')try{select.showPicker();}catch{}return;}
    if(action==='routes'){participationStart.candidate=integrated[0]?.id||null;rememberParticipation();renderParticipationStart();if(!integrated.length)location.hash='opportunities';return;}
    if(action==='details')return openCandidate(flow.candidate.id);
    if(action==='settings'){location.hash='agents';return;}
    if(action==='configure')return openExecution(flow.plan);
    if(action==='plan')return openPreparation(flow.plan.id);
    if(action==='report')return openCheck(flow.check.id);
    if(action==='run-progress'){selectExecution(flow.run.id);location.hash='runs';return;}
    if(action==='check')await startSelectedCheck(flow.candidate.id);
  });actions.append(button);
  if(flow.check&&flow.phase==='checking'){
    const cancel=element('button','text-button','停止检查');cancel.type='button';cancel.addEventListener('click',()=>cancelAgentCheck(flow.check.id));actions.append(cancel);
  }
  if(['blocked','configure','report'].includes(flow.phase)){
    const again=element('button','text-button',unconfigured?'配置检查 Agent':'用所选 Agent 重新检查');again.type='button';
    again.disabled=unresolved||app.pending.has('agent-check');
    again.addEventListener('click',()=>unconfigured?location.hash='agents':startSelectedCheck(flow.candidate.id));actions.append(again);
  }
  if(['retry','stale'].includes(flow.phase)&&flow.plan){
    const previous=element('button','text-button','查看已有方案');previous.type='button';previous.addEventListener('click',()=>openPreparation(flow.plan.id));actions.append(previous);
  }
  if(flow.candidate){const detail=element('button','text-button','查看项目资料');detail.type='button';detail.addEventListener('click',()=>openCandidate(flow.candidate.id));actions.append(detail);}
  if(unresolved){const refresh=element('button','text-button','重新检测');refresh.type='button';refresh.addEventListener('click',()=>loadChecks());actions.append(refresh);}
  setText('start-error',participationStart.error);$('start-error').hidden=!participationStart.error;
  const ready=state.run_readiness?.ready||0;
  setText('start-availability',ready?`${ready} 个项目可进入运行设置。其他发现仍只是线索。`:`目前没有可以直接运行的项目。${integrated.length} 条已接入路线仍在准备；其余是资料线索。`);
  const summary=$('start-software-status');if(summary)setText('start-software-status',`可运行 ${ready} 个 · ${integrated.length-ready} 条已接入路线仍在准备`);
  updateCheckClocks();
}

$('start-project').addEventListener('change',event=>{participationStart.candidate=event.target.value||null;participationStart.error='';rememberParticipation();renderParticipationStart();});
$('start-agent').addEventListener('change',event=>{participationStart.host=event.target.value;participationStart.error='';rememberParticipation();renderParticipationStart();});
document.querySelectorAll('[data-start-participation]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();startParticipation();}));
renderParticipationStart();
