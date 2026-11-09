"""Daily admission limits for automatic research; manual checks only record usage.

CLI usage is returned after a turn: the automatic admission budget is not a
hard mid-generation cutoff. An overshooting automatic turn blocks later
automatic admissions. Manual checks keep their usage ledger without this cap.
"""
from __future__ import annotations
import datetime as dt
import json

DEFAULT_POLICY = {"daily_checks":2,"daily_tokens":120000,"reservation_tokens":30000}
ZONE = dt.timezone(dt.timedelta(hours=8))


def validate_policy(value):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_POLICY): raise ValueError("Invalid budget fields")
    for key,maximum in (("daily_checks",20),("daily_tokens",2000000),("reservation_tokens",200000)):
        if type(value[key]) is not int or not 0<=value[key]<=maximum: raise ValueError("Invalid budget value")
    if value["daily_checks"] and value["reservation_tokens"]<1000: raise ValueError("Reserve at least 1000 tokens for unreported usage")
    return dict(value)


def budget_state(db, instant=None):
    current=instant or dt.datetime.now(dt.timezone.utc)
    day=current.astimezone(ZONE).date().isoformat()
    row=db.execute("SELECT payload FROM settings WHERE key='agent_budget'").fetchone()
    policy=validate_policy(json.loads(row[0])) if row else dict(DEFAULT_POLICY)
    groups={kind:{"used_checks":0,"measured_tokens":0,"reserved_tokens":0,"unreported_checks":0} for kind in ("manual","automatic")}
    for row in db.execute("SELECT payload FROM agent_checks"):
        job=json.loads(row[0])
        if not job.get("attempts"): continue
        started=dt.datetime.fromisoformat(job.get("claimed_at",job["created_at"]))
        if started.astimezone(ZONE).date().isoformat()!=day: continue
        kind="automatic" if job.get("origin")=="automatic" else "manual"
        group=groups[kind];group["used_checks"]+=1
        usage=job.get("usage")
        if isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ("input_tokens","output_tokens")):
            group["measured_tokens"]+=usage["input_tokens"]+usage["output_tokens"]
        else:
            group["unreported_checks"]+=1
            if kind=="automatic":group["reserved_tokens"]+=job.get("reservation_tokens",policy["reservation_tokens"])
    automatic=groups["automatic"]
    allowed=automatic["used_checks"]<policy["daily_checks"] and automatic["measured_tokens"]+automatic["reserved_tokens"]+policy["reservation_tokens"]<=policy["daily_tokens"]
    remaining=max(0,policy["daily_checks"]-automatic["used_checks"])
    totals={key:sum(group[key] for group in groups.values()) for key in ("used_checks","measured_tokens","reserved_tokens","unreported_checks")}
    return {"day":day,"timezone":"Asia/Shanghai","policy":policy,**totals,
            "scope":"automatic_checks","manual":groups["manual"]|{"can_start":True,"limit_type":"none"},
            "automatic":automatic|{"can_start":allowed,"remaining_checks":remaining},
            "can_start":allowed,"manual_can_start":True,"remaining_checks":remaining,
            "limit_type":"automatic_admission_only","note":"预算仅约束后台自动检查，按北京时间每日重置。手动检查没有本地每日次数或token上限；未回报用量仍标为未知。模型服务商的账户额度由服务商管理。"}
