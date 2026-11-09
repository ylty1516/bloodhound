"""Versioned preparation plans and durable, side-effect-free recipe rehearsals.

This module deliberately has no command runner. Every project action is a mock;
unmet conditions block a rehearsal instead of manufacturing a successful run.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import threading

from .domain import assess, now, _url
from .store import _json
from .recommendations import trial_advice

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ("preflight", "prepare", "run", "verify", "deliver")


def validate_recipe(value):
    required = {"id", "version", "candidate_url", "candidate_identity", "name", "network", "artifact", "steps", "evidence", "limitations", "delivery"}
    if not isinstance(value, dict) or set(value) != required: raise ValueError("Invalid recipe fields")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", value["id"]) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["version"]): raise ValueError("Recipe needs a stable version")
    _url(value["candidate_url"])
    if not isinstance(value["candidate_identity"],str) or not 1<=len(value["candidate_identity"])<=512: raise ValueError("Recipe needs an explicit project/network identity")
    if value["network"] not in ("testnet", "mainnet", "devnet"): raise ValueError("Recipe needs a specific network")
    artifact = value["artifact"]
    if not isinstance(artifact, dict) or set(artifact) != {"url", "sha256", "version", "locally_verified"}: raise ValueError("Invalid artifact pin")
    _url(artifact["url"])
    if not re.fullmatch(r"[a-fA-F0-9]{64}", artifact["sha256"]) or not artifact["version"] or type(artifact["locally_verified"]) is not bool: raise ValueError("Artifact must have a concrete hash and version")
    if not isinstance(value["steps"], list) or [s.get("action") for s in value["steps"] if isinstance(s,dict)] != list(ACTIONS): raise ValueError("Recipe needs five ordered typed steps")
    for step in value["steps"]:
        if set(step) != {"action", "description", "verification"}: raise ValueError("Recipes cannot supply executable commands")
        if any(not isinstance(step[k],str) or not step[k].strip() or len(step[k])>1200 for k in ("description","verification")): raise ValueError("Invalid recipe step")
    if not isinstance(value["evidence"],list) or not value["evidence"] or len(value["evidence"])>10: raise ValueError("Recipe needs evidence")
    for url in value["evidence"]: _url(url)
    if not isinstance(value["limitations"],list) or any(not isinstance(x,str) or len(x)>1200 for x in value["limitations"]): raise ValueError("Invalid recipe limitations")
    if any(not isinstance(value[k], str) or not value[k] or len(value[k])>1200 for k in ("name","delivery")): raise ValueError("Invalid recipe description")
    return json.loads(_json(value))


class Workflows:
    def __init__(self, store, checks, recipes=None):
        self.store, self.checks = store, checks
        self.lock = threading.RLock()
        if recipes is None:
            recipes = [json.loads(p.read_text("utf-8")) for p in sorted((ROOT / "recipes").glob("*.json"))]
        self.recipes = [validate_recipe(r) for r in recipes]
        with store._connection(write=True) as db:
            db.execute("CREATE TABLE IF NOT EXISTS preparation_plans (id TEXT PRIMARY KEY, check_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS workflow_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def _material(self, job):
        candidate = self.store.get_candidate(job["candidate_id"])
        if not candidate: raise ValueError("Candidate not found")
        hardware = {k:self.store.hardware().get(k) for k in ("os","ram_gb","vram_gb","disk_free_gb","logical_cores")}
        profile = self.store.profile()
        recipe = next((r for r in self.recipes if r["candidate_url"] == candidate["url"] and r["candidate_identity"] == candidate["identity_key"]), None)
        assessment = assess(candidate, hardware, profile)
        fingerprint = hashlib.sha256(_json({"candidate":candidate,"hardware":hardware,"profile":profile,"recipe":recipe,"report":job["report"]}).encode()).hexdigest()
        report = job["report"]
        blockers = []
        if not job.get("current"): blockers.append("项目或个人条件已变化，需要重新核验")
        checked = dt.datetime.fromisoformat(job.get("finished_at",job["updated_at"]))
        if (dt.datetime.now(dt.timezone.utc)-checked).total_seconds()>48*3600: blockers.append("检查报告超过48小时，需要复核参与窗口和来源")
        if any(c["topic"] == "risk" and c["status"] == "fail" for c in report["checks"]): blockers.append("安全检查发现未解决的问题")
        if (job.get("recommendation") or trial_advice(report, candidate)).get("status") != "suggested_trial": blockers.append("尚未形成针对这个入口和版本的有效安全通过记录")
        blockers += ["检查待解决："+c["finding"] for c in report["checks"] if c["status"] != "pass"]
        if candidate["classification"] not in ("unissued","unlisted_supported"): blockers.append("未满足有证据支持的未发行／未现货交易筛选条件")
        blockers += report["missing_information"]
        if assessment["status"] != "compatible": blockers += ["条件待确认："+s for s in assessment["missing"]]
        if assessment["status"] == "incompatible": blockers += assessment["reasons"]
        if not recipe: blockers.append("尚无这个项目的固定版本执行配方")
        elif not recipe["artifact"]["locally_verified"]: blockers.append("发布包尚未完成本机哈希核对与来源审阅")
        blockers = list(dict.fromkeys(blockers))
        return candidate, recipe, assessment, fingerprint, blockers

    def plans(self):
        result=[]
        jobs=self.checks.jobs()
        for research in self.store.research_jobs():
            reviewed=research.get("result") or {}
            if research["status"]!="resolved" or not reviewed.get("report"): continue
            current=self.store.get_candidate(research["candidate_id"])
            jobs.append({"id":"review_"+research["id"],"candidate_id":research["candidate_id"],"status":"completed","report":reviewed["report"],
                         "updated_at":reviewed["at"],"finished_at":reviewed["at"],"host":reviewed["host"],"current":current==reviewed["candidate"],
                         "fact_sync":{"status":"applied","reason":"当前宿主已提交带来源的研究资料与报告；没有另行启动模型检查"}})
        jobs.sort(key=lambda j:j.get("finished_at",j["updated_at"]),reverse=True)
        for job in jobs:
            if job["status"] != "completed" or not job.get("report"): continue
            candidate, recipe, assessment, fingerprint, blockers = self._material(job)
            recommendation = job.get("recommendation") or trial_advice(job["report"], candidate, job.get("finished_at"), job.get("current", False))
            status = "not_recommended" if recommendation["status"] in ("security_concern", "unavailable") else "needs_information" if blockers else "ready_for_simulation"
            plan = {"id":"plan_"+job["id"],"check_id":job["id"],"candidate_id":candidate["id"],"candidate_name":candidate["name"],
                "fingerprint":fingerprint,"status":status,"created_at":job.get("finished_at",job["updated_at"]),"host":job.get("host"),
                "summary":job["report"]["summary"],"fact_sync":job.get("fact_sync",{"status":"report_only","reason":"旧报告未提供结构化事实"}),
                "recommendation": recommendation, "category_label": {"pow":"传统挖矿", "node":"节点 / 算力贡献", "tasks":"测试网 / 空投任务"}[candidate["category"]],
                "blockers":blockers,"assessment":assessment,"recipe":recipe,"sources":job["report"]["sources"],"compute_profile":job["report"].get("compute_profile"),
                "next_steps":job["report"]["next_steps"],"execution_authorized":False,"live_execution_implemented":bool(recipe and recipe["id"] == "opacra-testnet"),
                "execution_drivers":["opacra-testnet-node", "opacra-testnet-cpu"] if recipe and recipe["id"] == "opacra-testnet" else []}
            with self.store._connection(write=True) as db:
                existing=db.execute("SELECT payload FROM preparation_plans WHERE id=?",(plan["id"],)).fetchone()
                if not existing or json.loads(existing[0]) != plan:
                    db.execute("INSERT INTO preparation_plans VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",(plan["id"],job["id"],_json(plan)))
            result.append(plan)
        return result

    def run(self, plan_id, key, fault_step=None, resume_id=None):
        if not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}",key): raise ValueError("A bounded idempotency key is required")
        if fault_step is not None and fault_step not in ACTIONS: raise ValueError("Unknown injected failure step")
        with self.lock:
            plan = next((p for p in self.plans() if p["id"]==plan_id),None)
            if not plan: raise ValueError("Preparation plan not found")
            ident=resume_id or "rehearsal_"+hashlib.sha256((plan_id+":"+key).encode()).hexdigest()[:24]
            with self.store._connection(write=True) as db:
                row=db.execute("SELECT payload FROM workflow_runs WHERE id=?",(ident,)).fetchone()
                old=json.loads(row[0]) if row else None
                if resume_id:
                    if not old or old["plan_id"]!=plan_id or old["status"] not in ("failed","cancelled"): raise ValueError("Only an interrupted rehearsal can resume")
                    if old["plan_fingerprint"]!=plan["fingerprint"]: raise ValueError("Plan changed; start a fresh rehearsal")
                elif old:
                    if old["plan_fingerprint"]!=plan["fingerprint"]: raise ValueError("Plan changed; use a fresh idempotency key")
                    return old | {"reused":True}
                blockers=plan["blockers"]
                steps = old["steps"] if old else [{"name":s["action"],"status":"pending","detail":s["description"],"verification":s["verification"]}
                                                    for s in (plan["recipe"] or {}).get("steps",[])]
                result={"id":ident,"plan_id":plan_id,"plan_fingerprint":plan["fingerprint"],"candidate_id":plan["candidate_id"],"candidate_name":plan["candidate_name"],
                    "mode":"simulation","at":now(),"status":"blocked" if blockers else "simulated","steps":steps,"checkpoint":old["checkpoint"] if old else 0,
                    "attempts":(old["attempts"] if old else 0)+1,"blockers":blockers,"assessment":plan["assessment"],"origin":"user",
                    "side_effects":False,"live_execution_allowed":False,"rewards":{"real":False,"amount":None,"unit":"none"}}
                if blockers:
                    for step in steps: step["status"]="blocked"
                else:
                    for i,step in enumerate(steps):
                        if i<result["checkpoint"]: continue
                        if step["name"]==fault_step:
                            step["status"]="failed";result["status"]="failed";result["failure"]="Injected simulation failure";break
                        step["status"]="mock";result["checkpoint"]=i+1
                db.execute("INSERT INTO workflow_runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",(ident,_json(result)))
                self.store._event(db,"recipe_rehearsal",{"id":ident,"status":result["status"],"checkpoint":result["checkpoint"],"side_effects":False})
                return result

    def cancel(self, ident):
        with self.lock, self.store._connection(write=True) as db:
            row=db.execute("SELECT payload FROM workflow_runs WHERE id=?",(ident,)).fetchone()
            if not row: raise ValueError("Unknown rehearsal")
            run=json.loads(row[0])
            if run["status"]=="failed":
                run["status"]="cancelled";db.execute("UPDATE workflow_runs SET payload=? WHERE id=?",(_json(run),ident))
            return run

    def runs(self):
        with self.store._connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM workflow_runs ORDER BY rowid DESC LIMIT 100")]
