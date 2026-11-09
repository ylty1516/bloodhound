import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
function fn(name){const at=source.indexOf(`function ${name}(`);const begin=source.slice(Math.max(0,at-6),at)==='async '?at-6:at;const after=source.indexOf('\nfunction ',at+1);const asyncAfter=source.indexOf('\nasync function ',at+1);return source.slice(begin,Math.min(...[after,asyncAfter].filter(n=>n>=0)));}
const app={state:null,pending:new Set(),mutationRevision:0};
const context=vm.createContext({app,AbortController,setTimeout,clearTimeout,Date,JSON,Array,Error,TypeError,Number});
vm.runInContext(fn('request'),context);
let calls=[];
context.fetch=async path=>{calls.push(path);return {status:calls.length===1?403:200,ok:calls.length!==1,json:async()=>({ok:true})};};
assert.equal((await context.request('/api/checks')).ok,true);
assert.deepEqual(calls,['/api/checks','/','/api/checks']);
calls=[];context.fetch=async path=>{calls.push(path);return {status:403,ok:false,json:async()=>({error:'denied'})};};
await assert.rejects(context.request('/api/checks'),/denied/);assert.equal(calls.length,2);

const renderers=['renderOverview','renderObservation','renderParticipation','renderCandidates','renderRuns','renderSources','renderEvents','renderSettings','renderCheckCenter','renderAgentModels','renderModelHistory','renderDeepSeek'];
const counts={};for(const name of renderers)context[name]=()=>{counts[name]=(counts[name]||0)+1;};
context.document={querySelectorAll:()=>[],activeElement:{},body:{}};context.$=()=>({open:false});context.setText=()=>{};context.array=v=>Array.isArray(v)?v:[];context.display=x=>x;
app.state={service:{version:'test'},candidates:[],sources:[],hardware:{},usage:{},observation:{status:'running'},profile:{},runs:[],scans:[],events:[],participation_requests:[],preparation_plans:[],agent_budget:{},host_compatibility:[]};
vm.runInContext(fn('renderAll'),context);context.renderAll();
const first={...counts};app.state.observation.elapsed_hours=1;context.renderAll();
for(const name of renderers.filter(n=>!['renderObservation','renderCheckCenter','renderModelHistory'].includes(n)))assert.equal(counts[name],first[name],`${name} rebuilt unchanged DOM`);

context.renderConnection=()=>{};context.notifyParticipation=()=>{};context.renderAll=()=>{};
let resolveRead;context.request=()=>new Promise(resolve=>{resolveRead=resolve;});
vm.runInContext(fn('loadState'),context);
const pending=context.loadState();
app.checksRevision=1;app.state.agent_checks=[{id:'one',status:'completed'}];app.state.agent_budget={used_checks:1};
resolveRead({service:{version:'test'},candidates:[],agent_checks:[{id:'one',status:'running'}],agent_budget:{used_checks:0}});
await pending;assert.equal(app.state.agent_checks[0].status,'completed');assert.equal(app.state.agent_budget.used_checks,1);
console.log(JSON.stringify({passed:4,checks:['local cookie renewal','bounded failed renewal','unchanged panels retain DOM','older full response cannot overwrite newer task status']}));
