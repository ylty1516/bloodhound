# Implementation contract 0.1

Runtime: Python 3.12 standard library, local HTTP at 127.0.0.1:18766. Existing mining-radar is read-only; no edits to its app/data/jobs. Source root is this prospect-agent directory. Runtime state defaults to LOCALAPPDATA/Prospect; tests use isolated temporary directories.

## File ownership

- Main: service.py, cli.py, sources.py, hardware.py, __init__.py, __main__.py, scripts, integration tests, shared docs.
- Domain agent: prospect/domain.py, prospect/store.py, tests/test_domain.py only.
- Adapter agent: adapters/** and tests/test_adapters.py only. No host config mutation without coordination.
- UI agent: web/index.html, web/app.js, web/styles.css only.

## Domain and store contract

domain.py exports normalize_candidate(data: dict)->dict, assess(candidate:dict,hardware:dict,profile:dict)->dict, simulate(candidate:dict,hardware:dict,profile:dict)->dict. normalize_candidate validates and returns id,name,category(pow/node/tasks),url,summary,evidence(list),market(dict token_issued/tge/mainnet/transferable/cex_spot/dex_spot/premarket: yes/no/unknown),requirements(dict min_ram_gb/min_disk_gb/min_vram_gb/os),reward_unit,participation(open/closed/unknown),checked_at,classification,confidence,identity_key. Market unknown is not proof of unlisted. Simulator has no external side effects, records explicit mock steps, never claims real rewards.

Store(path:Path) initializes SQLite WAL with connection per operation. Methods: upsert_candidate(data)->{id,changed}; candidates()->list[dict]; get_candidate(id)->dict|None; save_hardware(dict), hardware()->dict; save_profile(dict), profile()->dict; record_scan(dict), scans(limit=50)->list[dict]; add_run(dict)->dict (id added if absent), runs()->list[dict]; get_setting(key,default=None), set_setting(key,value); add_event(kind,payload)->dict; events(limit=50)->list[dict]; research_jobs()->list[dict]; resolve_research(id,result)->dict; usage()->dict. Changed candidates enqueue one research event per content revision; unchanged does not enqueue. No LLM calls. Usage shows 0 background model calls, host usage unknown unless provided; model execution is unavailable, not secretly simulated.

## HTTP API

All /api routes return JSON, failure {error:message}. GET /api/state returns {service:{version,mode,pid,started_at},hardware,profile,preferences,candidates:[candidate with assessment],sources:[{id,label,url,enabled,status,last_checked,last_success,etag,error,interval_seconds}],scans,runs,events,usage,observation,host_compatibility}. observation includes status/not_started|running|paused,start_at,elapsed_hours,target_hours:168,cycles,successes,expected_checks,coverage_pct,ready_for_review. Natural time and coverage permit review, never automatic completion. Preferences record idle_only/do_not_disrupt; live resource enforcement is not implemented. host_compatibility uses verified status labels.

GET /health is unauthenticated and includes only app/version/pid; other APIs require local session cookie or the private CLI control token. POST validates Host and same-origin for browser sessions. All HTML is rendered with textContent, no untrusted HTML injection.

POST /api/scan {} -> scan summary (read-only public sources, throttled).
POST /api/profile {electricity_price?,daily_hours?,cpu_limit_pct?,gpu_allowed?,max_daily_cost?,skill_level?,available_minutes?} -> saved profile. No secrets.
POST /api/simulate {candidate_id} -> clearly marked simulation result. No install/sign/pay/mining.
POST /api/import {} -> legacy import result (fixed allowlisted legacy DB only; custom path rejected).
POST /api/observation {action:'start'|'pause'|'resume'} -> observation status; runs deterministic monitoring only, not mining. Actual start coordinated by main agent.
POST /api/research/resolve {id,result} -> validates evidence and stores host-reviewed result, never approves execution.
POST /api/sources {id,enabled} -> toggles existing allowlisted source.
POST /api/shutdown {} -> stop this service only (CLI control token required).

## CLI and adapters

python -m prospect --data-dir PATH --port PORT serve|ensure|status|scan|hardware|import-legacy|candidates|research|ui|stop|doctor
python -m prospect --data-dir PATH --port PORT simulate CANDIDATE_ID
python -m prospect --data-dir PATH --port PORT tool NAME JSON

The tools are prospect_status, prospect_candidates, prospect_scan, prospect_assess, prospect_simulate, prospect_research_pending, prospect_research_resolve. They never execute a live project. Candidates accepts offset>=0 and limit1..50, returns {items,total,next_offset}. Research pending returns at most five pending revisions. Adapter SessionStart only calls ensure, suppresses incidental stdout and returns no large context. Native bridge CLI auto-ensures a service within a short timeout. Implemented MCP stdio bridge uses this same CLI, independent of host API credentials.

## UI

Chinese-first professional operations console. Sidebar with overview/opportunities/runs/evidence/settings; restrained monochrome + one teal accent; clear evidence/freshness states. Default real empty state and unknown status, never fake profits. Responsive, keyboard, 0/5/100 rows. Initial GET /api/state then refresh every 15s; no model calls. Candidate detail + simulate, manual scan, preferences, source toggles, observation controls. Show disabled live execution with honest '需要已验证配方与项目授权'.
