// Isolated application layout QA. Synthetic state is injected only into a new test tab.
// No product API request, source scan, observation, model, or project execution is allowed.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

const ROOT = path.resolve(import.meta.dirname, '..');
const portFile = path.join(process.env.LOCALAPPDATA, 'Prospect', 'qa-browser-20261106', 'DevToolsActivePort');
const debugPort = Number(fs.readFileSync(portFile, 'utf8').split('\n')[0]);
const origin = `http://127.0.0.1:${debugPort}`;
const created = await (await fetch(`${origin}/json/new?about:blank`, {method:'PUT'})).json();
const ws = new WebSocket(created.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
const pending = new Map();
const exceptions = [];
let nextId = 1;
ws.onmessage = event => {
  const value = JSON.parse(event.data);
  if (value.method === 'Runtime.exceptionThrown') exceptions.push(value.params.exceptionDetails.text);
  const request = pending.get(value.id);
  if (!request) return;
  pending.delete(value.id); clearTimeout(request.timer);
  value.error ? request.reject(Error(JSON.stringify(value.error))) : request.resolve(value.result);
};
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = nextId++;
    const timer = setTimeout(() => { pending.delete(id); reject(Error(`CDP timeout: ${method}`)); }, 10000);
    pending.set(id, {resolve, reject, timer}); ws.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const value = await send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
  if (value.exceptionDetails) throw Error(value.exceptionDetails.text);
  return value.result.value;
}
async function waitFor(expression) {
  const end = Date.now() + 10000;
  while (Date.now() < end) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 80));
  }
  throw Error(`Condition timed out: ${expression}`);
}
async function screenshot(name) {
  const {data} = await send('Page.captureScreenshot', {format:'png', captureBeyondViewport:false});
  fs.writeFileSync(path.join(ROOT, 'evidence', `layout-${name}.png`), Buffer.from(data, 'base64'));
}
async function key(key, code, windowsVirtualKeyCode) {
  await send('Input.dispatchKeyEvent', {type:'keyDown', key, code, windowsVirtualKeyCode,
    nativeVirtualKeyCode:windowsVirtualKeyCode,...(key==='Enter'?{text:'\r',unmodifiedText:'\r'}:{})});
  await send('Input.dispatchKeyEvent', {type:'keyUp', key, code, windowsVirtualKeyCode});
}
function fixture(count) {
  return {
    service:{name:'Prospect UI FIXTURE',version:'synthetic-layout-test',mode:'read_only',live_execution:false},
    hardware:{cpu_name:'测试设备 / Fixture',os:'Windows fixture',arch:'x64',cpu_logical:8,ram_gb:16,disk_free_gb:100,vram_gb:6,gpus:[{name:'合成 GPU / Fixture'}]},
    profile:{daily_hours:1,cpu_limit_pct:20,gpu_allowed:false,skill_level:'beginner',available_minutes:10,max_daily_cost:0},
    preferences:{resource_strategy:'idle_only',priority:'do_not_disrupt',routine_choices:'use_recommended_defaults',enforcement:'live_execution_not_implemented'},
    candidates:Array.from({length:count}, (_,i) => ({
      id:`fixture-${i}`,name:i===0 ? `合成布局测试-${'超长中文项目名称'.repeat(30)}-${'A'.repeat(100)}` : `合成项目 ${String(i+1).padStart(3,'0')}`,
      summary:`仅用于界面测试，不是真实项目、机会或收益。${i===0 ? 'LongUnbrokenSummary'.repeat(20) : 'Synthetic fixture data.'}`,
      url:'https://example.com/fixture',category:['pow','node','tasks'][i%3],classification:'unknown',confidence:'low',
      participation:'unknown',reward_unit:'unknown',checked_at:'2026-11-06T00:00:00Z',market:{},requirements:{},
      evidence:[{url:'https://example.com/fixture',title:'合成证据，仅用于布局测试',checked_at:'2026-11-06T00:00:00Z',kind:'fixture'}],
      assessment:{status:'unknown',reasons:['合成数据不构成适配结论'],missing:['参与状态','资源要求']}
    })),
    sources:[],scans:[],runs:[],events:[],host_compatibility:[],
    usage:{background_model_calls:0,input_tokens:0,output_tokens:0,cached_tokens:0,research_pending:count,host_usage:'unknown'},
    observation:{status:'not_started',target_hours:168,elapsed_hours:0,cycles:0,successes:0,coverage_pct:0}
  };
}
let injection;
let navigation = 0;
async function load(count, width, height, initialFailure = false) {
  if (injection) await send('Page.removeScriptToEvaluateOnNewDocument', {identifier:injection});
  const source = `(() => {
    const state = ${JSON.stringify(fixture(count))};
    window.__layoutFixture = {fail:${initialFailure}, state, requests:[], blocked:[]};
    window.fetch = async (input, options={}) => {
      const url = new URL(typeof input==='string' ? input : input.url, location.href);
      const qa=window.__layoutFixture;
      qa.requests.push({path:url.pathname, method:options.method||'GET'});
      if(url.pathname!=='/api/state'||(options.method && options.method!=='GET')) {
        qa.blocked.push(url.pathname); throw new Error('Fixture blocks all non-state API requests');
      }
      if(qa.fail) throw new TypeError('Simulated fixture offline state');
      return new Response(JSON.stringify(qa.state), {status:200,headers:{'Content-Type':'application/json'}});
    };
    document.addEventListener('DOMContentLoaded',()=>{
      const note=document.createElement('aside'); note.id='layout-fixture-note';
      note.textContent='合成布局测试 · ${count} 条 · 不是真实项目';
      Object.assign(note.style,{position:'fixed',bottom:'4px',right:'4px',zIndex:'9999',background:'#fff1c9',color:'#583d05',padding:'6px 9px',font:'11px sans-serif',border:'1px solid #d5b263',borderRadius:'3px',pointerEvents:'none'});
      document.body.append(note);
    });
  })();`;
  injection = (await send('Page.addScriptToEvaluateOnNewDocument', {source})).identifier;
  await send('Emulation.setDeviceMetricsOverride', {width,height,deviceScaleFactor:1,mobile:width<640});
  await send('Page.navigate', {url:`http://127.0.0.1:18766/?layout_fixture=${++navigation}#opportunities`});
  await waitFor(initialFailure ? "document.querySelector('#connection-label')?.textContent==='本地服务连接异常'" : `document.querySelector('#metric-candidates')?.textContent==='${count}'`);
  await waitFor("document.querySelector('#layout-fixture-note')");
}
async function bounds() {
  return evaluate(`(() => {
    const viewport=window.innerWidth;
    return {viewport,scrollWidth:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('body *')].filter(e=>{
      if(e.closest('[hidden]')||e.closest('dialog:not([open])')) return false;
      const r=e.getBoundingClientRect(),s=getComputedStyle(e);
      return s.display!=='none'&&s.visibility!=='hidden'&&r.width>1&&(r.right>viewport+1||r.left<-1);
    }).map(e=>({tag:e.tagName,id:e.id,className:e.className})).slice(0,12)};
  })()`);
}

const report = {scope:'synthetic UI fixtures only; no live API calls or runtime changes',checked_at:new Date().toISOString(),cases:[],errors:[]};
try {
  await send('Page.enable'); await send('Runtime.enable');
  for (const count of [0,5,100]) {
    for (const [width,height] of [[1440,1000],[390,844],[320,740]]) {
      await load(count,width,height);
      const layout=await bounds();
      const rows=await evaluate("document.querySelectorAll('#candidate-list tbody tr').length");
      report.cases.push({count,width,height,rows,layout});
      assert.equal(rows,count,`Rows at ${count}/${width}`);
      assert.ok(layout.scrollWidth<=width,`Horizontal page overflow at ${count}/${width}: ${layout.scrollWidth}`);
      assert.deepEqual(layout.overflow,[],`Clipped content at ${count}/${width}`);
      if(width===1440 || (count===100 && width===390)) await screenshot(`${count}-${width}`);
    }
  }
  await load(5,390,844);
  await send('Page.bringToFront');
  await evaluate("window.__layoutFixture.keys=[];document.addEventListener('keydown',e=>window.__layoutFixture.keys.push({key:e.key,tag:e.target.tagName,className:e.target.className}));");
  await evaluate("document.querySelector('#candidate-list .project-name-button').focus()");
  await key('Enter','Enter',13);
  await waitFor("document.querySelector('#candidate-dialog').open");
  report.dialog=await evaluate(`(()=>{const d=document.querySelector('#candidate-dialog'),h=document.querySelector('.dialog-header'),b=document.querySelector('#candidate-detail'),c=document.querySelector('#close-detail');return{viewportHeight:innerHeight,dialogHeight:d.getBoundingClientRect().height,headerHeight:h.getBoundingClientRect().height,bodyHeight:b.getBoundingClientRect().height,closeRect:{top:c.getBoundingClientRect().top,bottom:c.getBoundingClientRect().bottom},horizontalOverflow:d.scrollWidth>d.clientWidth}})()`);
  await screenshot('long-name-dialog-390');
  assert.ok(report.dialog.bodyHeight>=100,'Long title leaves no usable detail body');
  assert.ok(report.dialog.closeRect.top>=0 && report.dialog.closeRect.bottom<=844,'Close action hidden');
  assert.equal(report.dialog.horizontalOverflow,false,'Dialog horizontal overflow');
  await key('Escape','Escape',27);
  await waitFor("!document.querySelector('#candidate-dialog').open");
  report.keyboard={enter_opens:true,escape_closes:true,focus_restored:await evaluate("document.activeElement===document.querySelector('#candidate-list .project-name-button')")};
  assert.equal(report.keyboard.focus_restored,true,'Modal must return focus');
  await evaluate("document.querySelector('#refresh-button').click()");
  await waitFor("!document.querySelector('#refresh-button').disabled");
  report.keyboard.focus_survives_refresh=await evaluate("document.activeElement===document.querySelector('#candidate-list .project-name-button')");
  assert.equal(report.keyboard.focus_survives_refresh,true,'Automatic refresh must preserve row focus');
  await evaluate("window.__layoutFixture.fail=true;document.querySelector('#refresh-button').click()");
  await waitFor("document.querySelector('#connection-label').textContent==='本地服务连接异常'");
  report.offline={rows_preserved:await evaluate("document.querySelectorAll('#candidate-list tbody tr').length"),banner_visible:await evaluate("!document.querySelector('#connection-banner').hidden"),scan_disabled:await evaluate("document.querySelector('#scan-button').disabled"),retained_message:await evaluate("document.querySelector('#connection-message').textContent.includes('保留上次同步的数据')")};
  assert.equal(report.offline.rows_preserved,5);assert.ok(report.offline.banner_visible&&report.offline.scan_disabled&&report.offline.retained_message);
  await screenshot('offline-390');
  await evaluate("window.__layoutFixture.fail=false;document.querySelector('#refresh-button').click()");
  await waitFor("document.querySelector('#connection-label').textContent==='本地服务已连接'");
  report.offline.recovers=true;
  await evaluate("window.__layoutFixture.state.profile={};document.querySelector('#refresh-button').click();location.hash='settings'");
  await waitFor("document.querySelector('#page-title').textContent==='档案与设置' && !document.querySelector('#refresh-button').disabled");
  report.preferences=await evaluate("({idle:document.querySelector('#runtime-preferences').textContent.includes('仅在电脑空闲时运行'),recommended:document.querySelector('#runtime-preferences').textContent.includes('使用推荐默认值'),not_enforced:document.querySelector('#resource-enforcement').textContent.includes('当前没有执行资源限额'),unknown_skill:document.querySelector('[name=skill_level]').value==='',unknown_electricity:document.querySelector('[name=electricity_price]').value===''})");
  assert.ok(Object.values(report.preferences).every(Boolean),'Preferences or unknown user data incorrectly displayed');
  await evaluate("const hours=document.querySelector('[name=daily_hours]');hours.value='2';hours.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#refresh-button').click()");
  await waitFor("!document.querySelector('#refresh-button').disabled");
  report.preferences.unsaved_edit_preserved=await evaluate("document.querySelector('[name=daily_hours]').value==='2'");
  assert.ok(report.preferences.unsaved_edit_preserved);
  assert.deepEqual((await bounds()).overflow,[]);
  await screenshot('preferences-390');
  await load(0,390,844,true);
  report.initial_offline={empty:await evaluate("document.querySelector('#candidate-list').textContent.includes('尚未连接本地服务')"),scan_disabled:await evaluate("document.querySelector('#scan-button').disabled")};
  assert.ok(report.initial_offline.empty&&report.initial_offline.scan_disabled);
  assert.deepEqual(await evaluate("window.__layoutFixture.blocked"),[]);
  assert.deepEqual(exceptions,[]);
  report.js_errors=exceptions;report.passed=true;
} catch(error) {
  report.passed=false;report.errors.push(error.message);console.error(error.message);
  report.js_errors=exceptions;
  report.failure_state=await evaluate("({title:document.title,count:document.querySelector('#metric-candidates')?.textContent,connection:document.querySelector('#connection-message')?.textContent,active:document.activeElement?.className,keys:window.__layoutFixture?.keys})").catch(()=>null);
  process.exitCode=1;
} finally {
  fs.writeFileSync(path.join(ROOT,'evidence','layout-fixtures.json'),JSON.stringify(report,null,2));
  ws.close();
  await fetch(`${origin}/json/close/${created.id}`).catch(()=>{});
  console.log(JSON.stringify({passed:report.passed,cases:report.cases.length,errors:report.errors,report:'evidence/layout-fixtures.json'}));
}
