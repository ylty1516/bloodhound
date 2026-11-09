"use strict";
const economicMining = {state:null,fetching:false,busy:false,loginWindow:null};
const economicDriver = 'unmineable-usdt-bsc-vm-cpu';
function latestMiningRun(){return array(execution.state?.jobs||app.state?.executions?.jobs).find(j=>['unmineable-usdt-bsc-cpu',economicDriver].includes(j.driver?.id));}
function renderMining(){
  const state=economicMining.state||app.state?.economic_mining;if(!state)return;
  const job=latestMiningRun();const active=job&&executionActive.has(job.status);
  const evidence=job?.miner_evidence;const pool=job?.pool_after||job?.pool_before||state.pool;
  const login=state.wallet_login||{};
  setText('mining-wallet-status',state.wallet?.receive_verified?'币安收款地址已核实':state.wallet?.connected?'币安钱包已连接':'需要连接币安钱包');
  setText('mining-market',state.market?'USDT / BSC · 现货市场交易中':'只显示有交易与收款证据的路线');
  const runningNote=job?.contribution_verified?`矿池已接受 ${evidence?.accepted_shares||0} 个真实份额，正在核对收益记账。`:evidence?.hashrate_hs>0?`正在挖矿 · 当前 ${evidence.hashrate_hs.toFixed(1)} H/s · 等待矿池接受有效份额。`:job?.message;
  setText('mining-progress',active?runningNote:state.status==='checking'?state.message:job?job.message:state.message||'先自动核对钱包、交易通道和矿池，然后确认一轮运行。');
  setText('mining-shares',evidence?String(evidence.accepted_shares):'—');
  setText('mining-hashrate-label',active?'当前算力':job?'结束前算力':'本轮算力');
  setText('mining-hashrate',typeof evidence?.hashrate_hs==='number'?`${evidence.hashrate_hs.toFixed(1)} H/s`:'等待算力');
  setText('mining-balance',pool?.balance??'—');
  setText('mining-paid',job?.delivery?.onchain_verified?'已核验到账':'尚未到账');
  setText('mining-threshold',pool?`付款门槛 ${pool.threshold} USDT · 当前矿池累计 ${pool.balance} USDT${pool.auto_pay?' · 自动结算已开启':' · 启动时开启达到门槛后的自动结算'}。矿池余额不是钱包到账。`:'接受算力、矿池记账、钱包到账分开核验。');
  const address=active?job.inputs?.public_address:state.wallet?.address;
  setText('mining-address',address?`BSC 收款地址：${address}\nUSDT 合约：${state.route.contract}`:'从你的币安 Agent 钱包自动读取 BSC 收款地址，无需手填。');
  const primary=$('mining-primary');primary.disabled=economicMining.busy||state.status==='checking'||state.evidence_ready&&!state.environment_ready;
  const finished=job?.status==='completed'&&job.contribution_verified;
  setText('mining-title',finished?'这一轮，已经有结果。':active?'正在运行，进度在这里。':'从这里，跑完第一轮。');
  setText('mining-primary',active?'查看正在运行的这一轮':finished?'查看这轮结果':state.needs_wallet_login&&login.supported?'连接币安钱包':state.status==='checking'?'正在自动准备…':state.evidence_ready&&!state.environment_ready?'独立环境准备中…':state.ready?'开始 15 分钟真实挖矿':'准备真实挖矿');
  $('mining-new-run').hidden=!finished;$('mining-new-run').disabled=economicMining.busy||!state.ready;
  setText('mining-yield-note',job?.pool_credit_verified?`本轮矿池记账 ${job.pool_credit_delta} USDT。实际收益很低，请结合电费和付款门槛判断是否继续。`:'');
  $('mining-yield-note').hidden=!job?.pool_credit_verified;
  $('mining-connect').hidden=!login.supported;$('mining-connect').disabled=['starting','waiting'].includes(login.status);
  $('mining-login-block').hidden=!['starting','waiting','error'].includes(login.status);
  setText('mining-login-message',login.message||'');setText('mining-pairing-code',login.pairing_code||'');
  const url=$('mining-login-url');url.hidden=!login.url;
  if(login.url){url.href=login.url;if(economicMining.loginWindow&&!economicMining.loginWindow.closed){economicMining.loginWindow.location.href=login.url;economicMining.loginWindow=null;}}
  if(['connected','error'].includes(login.status)&&economicMining.loginWindow&&!economicMining.loginWindow.closed){economicMining.loginWindow.close();economicMining.loginWindow=null;}
  $('mining-stop').hidden=!active;$('mining-stop').disabled=economicMining.busy||job?.status==='stopping';
  $('mining-refresh').disabled=economicMining.busy||state.status==='checking'||active;
  const completed={prepare:state.ready||Boolean(job),run:job?.contribution_verified,credit:job?.pool_credit_verified,paid:job?.delivery?.onchain_verified};
  for(const [step,done] of Object.entries(completed))$('mining-step-'+step).className=done?'done':active&&step==='run'?'current':'';
}
async function loadMining(){
  if(economicMining.fetching||document.hidden)return;economicMining.fetching=true;
  try{economicMining.state=await request('/api/mining');renderMining();}
  catch(error){setText('mining-progress','连接中断：'+error.message);}
  finally{economicMining.fetching=false;}
}
async function prepareMining(){
  if(economicMining.busy)return;economicMining.busy=true;renderMining();
  try{economicMining.state=await request('/api/mining/refresh',{});renderMining();}
  catch(error){toast(error.message,true);}
  finally{economicMining.busy=false;renderMining();}
}
async function connectMiningWallet(){
  if(economicMining.busy)return;
  economicMining.busy=true;economicMining.loginWindow=window.open('about:blank','prospect-wallet-login');renderMining();
  try{await request('/api/wallet/connect',{confirmed:true});await loadMining();}
  catch(error){if(economicMining.loginWindow&&!economicMining.loginWindow.closed)economicMining.loginWindow.close();economicMining.loginWindow=null;toast(error.message,true);}
  finally{economicMining.busy=false;renderMining();}
}
function openEconomicMining(){
  if(!economicMining.state?.ready){location.hash='requests';prepareMining();return;}
  openExecution({candidate_name:'CPU 挖矿 → USDT → 币安 Agent 钱包',execution_drivers:[economicDriver],mining_route:true});
}
$('mining-primary').addEventListener('click',()=>{
  const job=latestMiningRun();
  if(job&&executionActive.has(job.status)){selectExecution(job.id);location.hash='runs';return;}
  if(job?.status==='completed'&&job.contribution_verified){selectExecution(job.id);location.hash='runs';return;}
  if(economicMining.state?.needs_wallet_login&&economicMining.state?.wallet_login?.supported){connectMiningWallet();return;}
  if(economicMining.state?.ready)openEconomicMining();else prepareMining();
});
$('mining-refresh').addEventListener('click',prepareMining);
$('mining-new-run').addEventListener('click',openEconomicMining);
$('mining-connect').addEventListener('click',connectMiningWallet);
$('mining-stop').addEventListener('click',async()=>{
  const job=latestMiningRun();if(!job||economicMining.busy)return;economicMining.busy=true;renderMining();
  try{await request('/api/executions/cancel',{id:job.id});await loadExecutions();}
  catch(error){toast(error.message,true);}
  finally{economicMining.busy=false;renderMining();}
});
loadMining();setInterval(loadMining,2000);
