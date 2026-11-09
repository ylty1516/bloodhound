"""Cited report facts -> candidate revision. No execution instructions are accepted."""
from __future__ import annotations

import json
import urllib.parse

from .domain import MARKET_FIELDS, assess, normalize_candidate, now, _number, _url

NUMBER_FIELDS = {"min_ram_gb", "min_disk_gb", "min_vram_gb", "daily_hours", "available_minutes", "estimated_daily_cost"}
FACT_FIELDS = tuple(["market." + k for k in MARKET_FIELDS] + ["requirements." + k for k in sorted(NUMBER_FIELDS)] +
                    ["requirements.os", "requirements.skill_level", "participation", "reward_unit"])


def fact_value(field, value):
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise ValueError("Fact value must be bounded text")
    if field.startswith("market."):
        if value not in ("yes", "no", "unknown"): raise ValueError("Invalid market fact")
    elif field == "participation":
        if value not in ("open", "closed", "unknown"): raise ValueError("Invalid participation fact")
    elif field == "requirements.skill_level":
        if value not in ("beginner", "intermediate", "advanced", "unknown"): raise ValueError("Invalid skill fact")
        return None if value == "unknown" else value
    elif field == "requirements.os":
        if value == "unknown": return []
        systems = sorted(set(v.strip().lower() for v in value.split(",")))
        if not systems or any(s not in ("windows", "linux", "darwin") for s in systems): raise ValueError("Invalid OS fact")
        return systems
    elif field.startswith("requirements."):
        if value == "unknown": return None
        try: number = float(value)
        except ValueError: raise ValueError("Numeric fact required") from None
        return _number(number, field, {"requirements.daily_hours": 24, "requirements.available_minutes": 1440}.get(field))
    return value


def validate_facts(bundle, report):
    if bundle is None: return None
    if not isinstance(bundle, dict) or set(bundle) != {"identity_matches_candidate", "official_url", "facts"}:
        raise ValueError("Invalid project fact bundle")
    if type(bundle["identity_matches_candidate"]) is not bool: raise ValueError("Identity match must be boolean")
    if bundle["official_url"]: _url(bundle["official_url"])
    facts = bundle["facts"]
    if not isinstance(facts, list) or len(facts) > len(FACT_FIELDS): raise ValueError("Too many project facts")
    urls = {s["url"] for s in report["sources"]}
    seen = set()
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {"field", "value", "sources", "kind", "scope", "note"}: raise ValueError("Invalid fact entry")
        if fact["field"] not in FACT_FIELDS or fact["field"] in seen: raise ValueError("Unsupported or duplicate fact field")
        seen.add(fact["field"])
        fact_value(fact["field"], fact["value"])
        if fact["kind"] not in ("official", "primary"): raise ValueError("Facts require primary evidence")
        if not isinstance(fact["sources"], list) or not fact["sources"] or len(fact["sources"]) > 4 or any(not isinstance(u, str) or u not in urls for u in fact["sources"]):
            raise ValueError("Every fact must cite report sources")
        if not isinstance(fact["note"], str) or not fact["note"].strip() or len(fact["note"]) > 1000: raise ValueError("Fact needs a bounded explanation")
        if not isinstance(fact["scope"], str) or len(fact["scope"]) > 500: raise ValueError("Invalid evidence scope")
        if fact["field"] in ("market.cex_spot", "market.dex_spot") and fact["value"] == "no" and not fact["scope"].strip():
            raise ValueError("Absence of trading requires an explicit checked scope")
    return bundle


def synchronize_report(store, db, job, report):
    """Apply an explicit, identity-matched fact bundle in the report transaction."""
    from .store import _json
    bundle = validate_facts(report.get("project_facts"), report)
    if not bundle or not bundle["facts"]:
        return {"status": "report_only", "reason": "报告未提供结构化事实，已保留结论；项目资料未改写"}, None
    identity = next(c for c in report["checks"] if c["topic"] == "identity")
    official = bundle["official_url"]
    if not bundle["identity_matches_candidate"] or identity["status"] != "pass" or not official:
        return {"status": "identity_unconfirmed", "reason": "候选身份与官方项目未确认一致，事实保留在报告中"}, None
    origin = urllib.parse.urlsplit(official).hostname
    if not any(urllib.parse.urlsplit(u).hostname == origin for u in identity["sources"]):
        return {"status": "identity_unconfirmed", "reason": "身份检查缺少官方域名对应的来源"}, None
    row = db.execute("SELECT payload,revision FROM candidates WHERE id=?", (job["candidate_id"],)).fetchone()
    candidate = json.loads(row["payload"])
    before = json.loads(row["payload"])
    evidence = list(candidate["evidence"])
    checked = now()
    for fact in bundle["facts"]:
        field, value = fact["field"], fact_value(fact["field"], fact["value"])
        # Unknown observations must not silently erase previously known information.
        if value in (None, "unknown") or value == []: continue
        if "." in field:
            section, key = field.split(".")
            candidate[section][key] = value
        else: candidate[field] = value
        for url in fact["sources"]:
            evidence.append({"url": url, "kind": fact["kind"], "checked_at": checked, "note": fact["note"], "scope": fact["scope"],
                             "claims": {field.split(".")[1]: value} if field.startswith("market.") else {}})
    # Preserve contrary prior claims. Exact fact duplicates are collapsed, never opposite values.
    unique = {}
    for e in evidence:
        unique[_json({k:v for k,v in e.items() if k != "checked_at"})] = e
    if len(unique) > 40:
        return {"status": "review_needed", "reason": "累计证据超过40条，需要整理后再合并；原始报告已保留"}, None
    candidate["evidence"] = list(unique.values())
    candidate["checked_at"] = checked
    candidate = normalize_candidate(candidate)
    if candidate["id"] != before["id"]: raise ValueError("Report cannot change candidate identity")
    assessment = assess(candidate, job["context"]["hardware"], job["context"]["profile"])
    from .recommendations import review_verdict
    report["verdict"] = review_verdict(report)
    research = db.execute("SELECT id FROM research WHERE candidate_id=? AND revision=?", (candidate["id"], row["revision"])).fetchone()
    if not research: return {"status": "review_needed", "reason": "当前研究修订不存在，资料未改写"}, None
    result = {"id": research["id"], "candidate_id": candidate["id"], "candidate": candidate, "status": "resolved", "at": checked,
              "agent_check_id": job["id"], "agent_verdict": report["verdict"], "review_method": "cited_agent_facts", "live_execution_allowed": False}
    db.execute("UPDATE candidates SET payload=?,updated_at=? WHERE id=?", (_json(candidate), checked, candidate["id"]))
    db.execute("UPDATE research SET status='resolved',result=? WHERE id=?", (_json(result), research["id"]))
    store._event(db, "agent_facts_applied", {"check_id": job["id"], "candidate_id": candidate["id"], "before": before,
                 "fields": [f["field"] for f in bundle["facts"]], "execution_authorized": False})
    return {"status": "applied", "reason": "带来源的事实已更新；符合条件时会自动生成参与请求", "research_id": research["id"]}, candidate
