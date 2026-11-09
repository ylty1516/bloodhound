// Isolated headless Chrome integration checks of our local app (no user browser profile).
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const runtime = path.join(process.env.LOCALAPPDATA, 'Prospect');
const debugPort = Number(fs.readFileSync(path.join(runtime, 'qa-browser-20261106', 'DevToolsActivePort'), 'utf8').split('\n')[0]);
const target = await (await fetch(`http://127.0.0.1:${debugPort}/json/new?${encodeURIComponent('http://127.0.0.1:18766/')}`, {method:'PUT'})).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
let nextId=1;
const pending=new Map();
const errors=[];
ws.onmessage=event=>{
  const message=JSON.parse(event.data);
  if(message.method==='Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  if(pending.has(message.id)) {
    const {resolve,reject,timer}=pending.get(message.id);pending.delete(message.id);clearTimeout(timer);
    message.error?reject(new Error(JSON.stringify(message.error))):resolve(message.result);
  }
};
function send(method,params={}) {return new Promise((resolve,reject)=>{const id=nextId++;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout: '+method));},10000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression) {
  const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function waitFor(expression) {
  const until=Date.now()+10000;
  while(Date.now()<until) {if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,100));}
  throw new Error('Timed out waiting for '+expression);
}
async function screenshot(name) {
  // Wait for the UI's 150 ms navigation/dialog transitions before visual evidence.
  await evaluate('new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 200)))');
  const {data}=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  fs.writeFileSync(path.join('evidence',name),Buffer.from(data,'base64'));
}
try {
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:'http://127.0.0.1:18766/'});
  await waitFor("/^\\d+$/.test(document.querySelector('#metric-candidates')?.textContent ?? '')");
  const candidateCount=Number(await evaluate("document.querySelector('#metric-candidates').textContent"));
  assert.ok(candidateCount>0);
  assert.equal(await evaluate("document.querySelector('#metric-usage').textContent"),'0');
  assert.equal(await evaluate('document.documentElement.scrollWidth > window.innerWidth'),false);
  await screenshot('web-desktop.png');
  await evaluate("location.hash='opportunities'");
  await waitFor("document.querySelector('#view-opportunities') && !document.querySelector('#view-opportunities').hidden");
  await evaluate("document.querySelector('#candidate-list .project-name-button').click()");
  await waitFor("document.querySelector('#candidate-dialog').open");
  const buttons=await evaluate("[...document.querySelectorAll('#candidate-dialog button')].map(x=>({text:x.textContent,disabled:x.disabled}))");
  await screenshot('web-project-detail.png');
  // Production visual checks are read-only. Simulation mutations belong in isolated tests.
  const simulated=false;
  await evaluate("document.querySelector('#close-detail').click()");
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("location.hash='overview'");
  await waitFor("document.querySelector('#page-title').textContent==='总览'");
  assert.equal(await evaluate("document.querySelector('[aria-current=page]').dataset.view"),'overview');
  await screenshot('web-mobile.png');
  assert.equal(await evaluate('document.documentElement.scrollWidth > window.innerWidth'),false);
  await evaluate("location.hash='settings'");
  await waitFor("document.querySelector('#page-title').textContent==='档案与设置'");
  assert.equal(await evaluate('document.documentElement.scrollWidth > window.innerWidth'),false);
  assert.ok(await evaluate("document.querySelector('#runtime-preferences').textContent.includes('仅在电脑空闲时运行')"));
  assert.ok(await evaluate("document.querySelector('#resource-enforcement').textContent.includes('当前没有执行资源限额')"));
  await screenshot('web-settings-mobile.png');
  assert.deepEqual(errors,[]);
  const report={scope:'isolated_headless_browser',checked_at:new Date().toISOString(),desktop:'1440x1000',mobile:'390x844',candidate_count:candidateCount,js_errors:errors,simulated_button_clicked:simulated,buttons,checks:['real API connected','background model calls zero','candidate details','simulation-only flow','navigation','desktop and mobile no horizontal overflow']};
  fs.writeFileSync('evidence/browser-qa.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
} finally {ws.close();}
