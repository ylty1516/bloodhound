"""Trial advice is separate from machine readiness and execution permission."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

POLICY_VERSION = "safety-first-v1"
LABELS = {"suggested_trial": "建议尝试", "audit_pending": "待安全核验",
          "security_concern": "存在安全问题", "unavailable": "参与窗口已关闭",
          "review_expired": "需要更新安全检查"}


def validate_audit(audit, urls, public_url):
    if audit is None:
        return
    keys = {"status", "target_url", "version", "scope", "findings", "sources"}
    if not isinstance(audit, dict) or not keys <= set(audit) or set(audit) - keys - {"method", "artifact_sha256"}:
        raise ValueError("Invalid safety audit fields")
    if "artifact_sha256" in audit and (not isinstance(audit["artifact_sha256"], str) or audit["artifact_sha256"] and not re.fullmatch(r"[a-f0-9]{64}", audit["artifact_sha256"])):
        raise ValueError("Invalid audited artifact SHA-256")
    method = audit.get("method", "source_review")
    if method not in ("source_review", "official_web"):
        raise ValueError("Invalid safety audit method")
    if audit["status"] not in ("pass", "fail", "unknown"):
        raise ValueError("Invalid safety audit status")
    for key in ("target_url", "version", "scope"):
        if not isinstance(audit[key], str) or len(audit[key]) > 2000:
            raise ValueError("Invalid safety audit text")
    if audit["target_url"]:
        public_url(audit["target_url"])
    if not isinstance(audit["findings"], list) or len(audit["findings"]) > 12 or any(not isinstance(s, str) or len(s) > 1200 for s in audit["findings"]):
        raise ValueError("Invalid safety audit findings")
    if not isinstance(audit["sources"], list) or any(not isinstance(u, str) or u not in urls for u in audit["sources"]):
        raise ValueError("Audit citations must refer to supplied evidence")
    if audit["status"] == "pass" and (not audit["target_url"] or not audit["scope"].strip() or not audit["sources"]
            or method == "source_review" and audit["version"].strip().lower() in ("", "unknown", "latest", "main", "master", "head", "未知", "未核验")):
        raise ValueError("A passed audit needs a specific target, fixed version, scope and evidence")


def review_verdict(report):
    """Do not collapse hardware, costs or missing information into a rejection."""
    checks = {c["topic"]: c for c in report["checks"]}
    audit = report.get("safety_audit") or {}
    if checks["risk"]["status"] == "fail" or audit.get("status") == "fail":
        return "unsuitable"
    if checks["availability"]["status"] == "fail":
        return "unsuitable"
    if audit.get("status") == "pass" and checks["risk"]["status"] == "pass" and (audit.get("method") != "official_web" or checks["identity"]["status"] == "pass"):
        return "suitable"
    return "needs_info"


def trial_advice(report, candidate, checked_at=None, project_current=True):
    checks = {c["topic"]: c for c in report.get("checks", [])}
    audit = report.get("safety_audit") or {}
    risk = checks.get("risk", {})
    status, reason = "audit_pending", "尚无针对这个参与入口与版本的安全检查；资料不足不代表不值得尝试。"
    if risk.get("status") == "fail" or audit.get("status") == "fail":
        status = "security_concern"
        reason = risk.get("finding") if risk.get("status") == "fail" else "；".join(audit.get("findings", []))
        reason = reason or "安全检查发现问题，先查看具体发现。"
    elif candidate.get("participation") == "closed" or checks.get("availability", {}).get("status") == "fail":
        status, reason = "unavailable", checks.get("availability", {}).get("finding") or "当前参与窗口已关闭。"
    elif audit.get("status") == "pass" and risk.get("status") == "pass" and audit.get("target_url", "").rstrip("/") == candidate.get("url", "").rstrip("/") and (audit.get("method") != "official_web" or candidate.get("category") == "tasks" and checks.get("identity", {}).get("status") == "pass"):
        status, reason = "suggested_trial", "所列范围的安全检查已通过，可考虑小规模尝试；硬件、成本和维护条件单独提示。"
        if not project_current:
            status, reason = "review_expired", "项目资料发生变化，需要核对安全检查是否仍适用；设备变化不会单独否决建议。"
        if checked_at:
            try:
                expired = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(checked_at) > dt.timedelta(hours=48)
            except (ValueError, TypeError):
                expired = True
            if expired:
                status, reason = "review_expired", "安全检查超过48小时，请确认入口、版本与风险信息是否变化。"
    notes = [c["finding"] for topic, c in checks.items() if topic in ("hardware", "effort", "cost", "market", "availability") and c["status"] != "pass"]
    if candidate.get("classification") == "listed":
        notes.insert(0, "已有现货交易；还需核对币安 Agent 钱包的具体收款网络、资产与结算路线。")
    return {"status": status, "label": LABELS[status], "reason": reason, "notes": notes,
            "hardware_is_advisory": True, "policy": POLICY_VERSION,
            "audit": audit or None, "execution_authorized": False}


def trial_request(plan):
    advice = plan.get("recommendation") or {}
    if advice.get("status") != "suggested_trial": return None
    revision = hashlib.sha256(json.dumps({"candidate": plan["candidate_id"], "audit": advice["audit"],
        "notes": advice["notes"], "policy": POLICY_VERSION}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"id": f"request_{plan['candidate_id']}_{revision[:16]}", "candidate_id": plan["candidate_id"],
        "candidate_name": plan["candidate_name"], "status": "pending", "created_at": plan["created_at"], "revision": revision,
        "reasons": [advice["reason"], "硬件匹配不影响尝试建议；实际运行前再选择设备和资源范围。"],
        "plan": {"category_label": plan.get("category_label", "项目尝试"),
            "resources": [{"name": "硬件策略", "value": "当前仅作参考，可另选合适设备"}],
            "runtime": "按尝试计划安排", "maintenance": "单独确认维护安排", "required_skill": "可由 Agent 辅助准备",
            "estimated_cost": "费用单独列出，建议尝试不代表同意付费", "reward": "奖励与可兑现价值保持独立核验",
            "delivery": "先约定可核验的贡献或任务回执", "unknowns": advice["notes"],
            "execution_note": "表达意向后准备具体方案；不会自动安装或启动项目。"},
        "evidence": [{"url": s["url"], "kind": "review", "note": s["note"], "checked_at": plan["created_at"]} for s in plan["sources"]],
        "blockers": plan["blockers"], "readiness": "trial_review_only", "preparation_plan_id": plan["id"]}
