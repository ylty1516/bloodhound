"use strict";

const executionNames = {queued:"等待启动",waiting_idle:"等待电脑空闲",preparing:"准备文件",running:"正在运行",stopping:"正在停止",verifying:"核验结果",completed:"已完成",cancelled:"已停止",timed_out:"达到时长上限",failed:"运行失败",interrupted:"服务曾中断",paused:"因电脑使用而停止"};
const executionActive = new Set(["queued","waiting_idle","preparing","running","stopping","verifying"]);
const execution = {state:null, selected:null, cursor:0, fetching:false, busy:false, quote:null, previewSerial:0, logFetching:false};

function renderExecutions() {
  if(!execution.state && app.state?.executions) execution.state=app.state.executions;
  const jobs=array(execution.state?.jobs);
  if(typeof renderMining==='function')renderMining();
  const projects=jobs.filter(j=>j.mode!=='diagnostic');
  const diagnostics=jobs.filter(j=>j.mode==='diagnostic');
  const active=jobs.filter(j=>executionActive.has(j.status));
  const liveActive=active.filter(j=>j.mode!=='diagnostic');
  setText("execution-summary",liveActive.length ? `${liveActive.length} 个项目进行中 · 离开页面后继续运行` : "真正启动后的项目，进度和结果都会显示在这里。");
  const signature=JSON.stringify(jobs.map(j=>[j.id,j.status,j.message]));
  if($('execution-list').dataset.signature!==signature){
    const focus=document.activeElement?.id;
    $('execution-list').dataset.signature=signature;
    const rowFor=job=>{
      const row=element('button','execution-row');row.type='button';row.id=`select-${job.id}`;
      const name=element('span','execution-row-name');append(name,element('strong','',job.driver.name),element('small','muted',`${job.mode==='diagnostic'?'本机自检 · 不参与项目':'实际项目进程 · '+job.driver.network} · ${date(job.created_at)}`));
      append(row,name,badge(executionNames[job.status]||job.status,job.status==='failed'?'warning':executionActive.has(job.status)?'teal':''));
      row.addEventListener('click',()=>selectExecution(job.id));return row;
    };
    $('execution-list').replaceChildren(...(projects.length ? projects.map(rowFor):[empty('还没有启动真实项目','先选一个项目，让 Agent 检查；有可用的运行方式并满足启动条件后，在同一页继续。',{label:'选择项目，开始参与',run:()=>startParticipation()})]));
    $('diagnostic-list').replaceChildren(...diagnostics.map(rowFor));
    if(focus && $(focus))$(focus).focus({preventScroll:true});
  }
  if(!jobs.some(j=>j.id===execution.selected)) selectExecution(liveActive[0]?.id||projects[0]?.id||null);
  const job=jobs.find(j=>j.id===execution.selected);
  $('execution-detail').hidden=!job;
  document.querySelectorAll('.execution-row').forEach(row=>row.setAttribute('aria-pressed',String(row.id===`select-${execution.selected}`)));
  if(!job)return;
  setText('execution-title',job.driver.name);
  setText('execution-status',executionNames[job.status]||job.status);
  setText('execution-message',job.message);
  setText('execution-time',`运行 ${Math.round(job.elapsed_seconds||0)} 秒 / 上限 ${job.limits.duration_seconds} 秒 · CPU ≤ ${job.limits.cpu_percent}% · 内存 ≤ ${job.limits.memory_mb} MB`);
  const age=(Date.now()-Date.parse(job.heartbeat_at))/1000;
  setText('execution-heartbeat',executionActive.has(job.status) ? age>15 ? '暂未收到新的运行状态，正在重新连接…' : `最近心跳 ${Math.max(0,Math.round(age))} 秒前` : `结束于 ${date(job.finished_at)}`);
  $('execution-stop').hidden=!executionActive.has(job.status);
  $('execution-stop').disabled=job.status==='stopping'||execution.busy;
  $('execution-receipt').hidden=!job.receipt?.available;
  setText('execution-result',job.miner_evidence ? `矿池接受 ${job.miner_evidence.accepted_shares} 个份额 · 矿池余额 ${job.pool_after?.balance??job.pool_before?.balance??'待核对'} USDT · ${job.delivery?.onchain_verified?'钱包到账已核验':'钱包尚未到账'}` : job.diagnostic_verified ? '自检结果已核验。没有启动矿工，也没有产生奖励。' : job.node_evidence ? `测试网高度 ${job.node_evidence.height} · ${job.node_evidence.synchronized?'节点已同步':'节点同步中'} · 奖励尚未核验` : job.mode==='live' ? '等待矿池接受份额与收益证据。' : '自检完成后会核验结果文件，并生成可下载的回执。');
  const stages=[['queued','接收'],['prepare','准备'],['run','运行'],['verify','核验'],['finished','回执']];
  const step=job.stage==='waiting_idle'?0:Math.max(0,stages.findIndex(s=>s[0]===job.stage));
  $('execution-stages').replaceChildren(...stages.map(([key,label],index)=>element('span',index===step?'execution-stage current':'execution-stage',label)));
}

function selectExecution(id){
  if(execution.selected===id)return;
  execution.selected=id;execution.cursor=0;execution.logFetching=false;
  $('execution-log').textContent='';$('execution-log-empty').hidden=false;
  if(id){renderExecutions();loadExecutionLogs();}
}

async function loadExecutions(){
  if(execution.fetching||document.hidden)return;
  execution.fetching=true;
  try{execution.state=await request('/api/executions');renderExecutions();if(typeof renderParticipationStart==='function')renderParticipationStart();setText('execution-connection','实时连接');await loadExecutionLogs();}
  catch(error){setText('execution-connection',`连接中断：${error.message}`);}
  finally{execution.fetching=false;}
}

async function loadExecutionLogs(){
  const id=execution.selected;if(!id||execution.logFetching)return;
  execution.logFetching=true;
  try{
    const data=await request(`/api/executions/logs?id=${encodeURIComponent(id)}&after=${execution.cursor}`);
    if(execution.selected!==id)return;
    const log=$('execution-log');const atBottom=log.scrollHeight-log.clientHeight-log.scrollTop<45;
    if(data.lines.length){
      if(data.truncated)log.append(document.createTextNode('\n[较早的日志已超过保留范围]\n'));
      log.append(document.createTextNode(data.lines.map(l=>`${new Date(l.at).toLocaleTimeString('zh-CN',{hour12:false})}  ${l.line}`).join('\n')+'\n'));
      const lines=log.textContent.split('\n');if(lines.length>650)log.textContent=lines.slice(-650).join('\n');
      $('execution-log-empty').hidden=true;if(atBottom)log.scrollTop=log.scrollHeight;
    }
    execution.cursor=data.cursor;
  }catch(error){if(execution.selected===id)setText('execution-connection',`日志连接中断：${error.message}`);}
  finally{if(execution.selected===id)execution.logFetching=false;}
}

function openExecution(plan=null){
  execution.plan=plan;execution.quote=null;execution.busy=false;
  const drivers=plan?array(plan.execution_drivers):['local-self-check'];
  const names={'unmineable-usdt-bsc-vm-cpu':'隔离 CPU 挖矿 · USDT / BSC','unmineable-usdt-bsc-cpu':'CPU 挖矿 · USDT / BSC','local-self-check':'本机执行器自检','opacra-testnet-node':'CPU 节点试运行（无需钱包）','opacra-testnet-cpu':'CPU 挖矿（需要测试网收款地址）'};
  $('execution-driver').replaceChildren(...drivers.map(id=>{const o=element('option','',names[id]||id);o.value=id;return o;}));
  setText('execution-scope-title',plan?plan.candidate_name:'体验一次真实的本机运行');
  $('execution-duration').value=plan?'60':'20';$('execution-cpu').value=plan?'20':'10';$('execution-memory').value=plan?'2048':'256';$('execution-idle').checked=Boolean(plan);
  if(plan?.mining_route){$('execution-duration').value='900';$('execution-memory').value='3072';$('execution-idle').checked=false;}
  setText('execution-options-help',plan?.mining_route?'钱包和结算网络已自动带入。确认本轮资源范围即可，无需填写链上参数。':'先选节点试运行即可，不需要钱包或签名。资源已填推荐值。');
  $('execution-project-options').hidden=!plan;
  $('execution-driver').closest('label').hidden=Boolean(plan?.mining_route);
  $('execution-resource-options').open=false;
  $('execution-address').value='';$('execution-address-label').hidden=true;
  $('execution-quote').replaceChildren(element('p','quiet-note','正在读取本次运行范围…'));
  $('execution-start').disabled=true;
  openExclusiveDialog('execution-dialog');refreshExecutionPreview();
}

async function refreshExecutionPreview(){
  const serial=++execution.previewSerial;execution.quote=null;$('execution-start').disabled=true;
  const driver=$('execution-driver').value;
  $('execution-address-label').hidden=driver!=='opacra-testnet-cpu';
  const payload={driver,options:{duration_seconds:Number($('execution-duration').value),cpu_percent:Number($('execution-cpu').value),memory_mb:Number($('execution-memory').value),idle_only:$('execution-idle').checked},inputs:driver==='opacra-testnet-cpu'?{public_address:$('execution-address').value.trim()}:{}};
  setText('execution-defaults',`本次 ${payload.options.duration_seconds} 秒 · CPU 最高 ${payload.options.cpu_percent}% · 内存最多 ${payload.options.memory_mb} MB${payload.options.idle_only?' · 电脑空闲时开始':''}`);
  if(execution.plan)payload.plan_id=execution.plan.id;
  try{
    const quote=await request('/api/executions/preview',payload);if(serial!==execution.previewSerial)return;
    execution.quote=quote;
    const block=$('execution-quote');block.replaceChildren();
    if(quote.driver.id.startsWith('unmineable-usdt-bsc-')){
      append(block,element('h3','','收益结算到你的币安钱包'),element('p','','USDT · BSC 网络 · 矿池达到 1.5 USDT 后自动结算。'),element('p','quiet-note','本次只运行一轮。矿池费约 1% + 矿工捐赠 1%，电费另计，不保证盈利。'));
      const details=element('details','raw-details');append(details,element('summary','','核对收款地址与连接说明'),element('p','',quote.scope),element('p','quiet-note',quote.notes[2]));block.append(details);
    }else block.append(element('p','',quote.scope));
    if(quote.artifact){const source=element('details','raw-details');append(source,element('summary','','查看程序版本与来源'),element('p','quiet-note',`固定版本 ${quote.driver.version} · ${quote.driver.network==='mainnet'?'真实算力与主网收款':'测试网'}`),safeLink(quote.artifact.url,'查看发布包来源 ↗'));block.append(source);}
    if(quote.driver.id.startsWith('unmineable-usdt-bsc-'))block.append(element('p','quiet-note','接受份额、矿池记账和钱包到账会分别显示。'));
    if(quote.blockers.length){const list=element('ul','agent-next');quote.blockers.forEach(reason=>list.append(element('li','',reason)));const details=element('details','raw-details');append(details,element('summary','','查看具体缺项'),list);append(block,element('strong','','当前还未满足启动条件，需要先完成程序核验。'),details);}
    else block.append(element('p','execution-ready','本次运行范围已准备好。'));
    if(execution.plan)block.append(element('p','quiet-note',quote.containment));
    $('execution-start').disabled=!quote.ready;
    setText('execution-start',execution.plan?.mining_route?'确认本轮挖矿与矿池自动结算':execution.plan?'按此范围启动一次':'开始本机自检');
  }catch(error){if(serial!==execution.previewSerial)return;$('execution-quote').replaceChildren(element('p','inline-error',error.message));}
}

async function startExecution(){
  if(!execution.quote?.ready||execution.busy)return;
  execution.busy=true;$('execution-start').disabled=true;setText('execution-start','正在提交…');
  // A preview can produce at most one execution, even across retries/tabs.
  try{
    const job=await request('/api/executions/start',{quote_id:execution.quote.id,key:`web_${execution.quote.id}`,confirmed:true});
    $('execution-dialog').close();location.hash='runs';
    execution.selected=job.id;execution.cursor=0;$('execution-log').textContent='';
    await loadExecutions();toast('任务已提交，可以在这里看进度或随时停止。');
  }catch(error){toast(error.message,true);}
  finally{execution.busy=false;$('execution-start').disabled=!execution.quote?.ready;setText('execution-start',execution.plan?'按此范围启动一次':'开始本机自检');}
}

async function stopExecution(){
  if(execution.busy||!execution.selected)return;execution.busy=true;renderExecutions();
  try{await request('/api/executions/cancel',{id:execution.selected});await loadExecutions();}
  catch(error){toast(error.message,true);}finally{execution.busy=false;renderExecutions();}
}

$('execution-self-check').addEventListener('click',()=>openExecution());
$('execution-close').addEventListener('click',()=>$('execution-dialog').close());
$('execution-start').addEventListener('click',startExecution);
$('execution-stop').addEventListener('click',stopExecution);
$('execution-form').addEventListener('change',refreshExecutionPreview);
$('execution-form').addEventListener('submit',event=>{event.preventDefault();startExecution();});
$('execution-receipt').addEventListener('click',async()=>{
  try{const receipt=await request(`/api/executions/receipt?id=${encodeURIComponent(execution.selected)}`);const url=URL.createObjectURL(new Blob([JSON.stringify(receipt,null,2)],{type:'application/json'}));const link=element('a');link.href=url;link.download=`prospect-${receipt.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  catch(error){toast(error.message,true);}
});
setInterval(()=>{if(app.activeView==='runs'||array(execution.state?.jobs).some(j=>executionActive.has(j.status)))loadExecutions();},1500);
window.addEventListener('hashchange',()=>{if(location.hash==='#runs')loadExecutions();});
loadExecutions();
