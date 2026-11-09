"""Deterministic invitations to review a participation plan, never execution permission.

The caller must restrict this rule to host-reviewed, resolved candidates. An
``official`` label is a recorded research assertion, not proof of source identity
by this module. No model, network, process, wallet or filesystem operation occurs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from .domain import MARKET_FIELDS, assess, normalize_candidate, validate_profile

FRESHNESS = dt.timedelta(hours=48)
CLOCK_SKEW = dt.timedelta(minutes=5)
HARDWARE_FIELDS = {"min_ram_gb", "min_disk_gb", "min_vram_gb", "os", "participation"}
PROJECT_FIELDS = ("min_ram_gb", "min_disk_gb", "min_vram_gb", "daily_hours", "available_minutes", "skill_level")
CATEGORIES = {"pow": "传统挖矿", "node": "节点／算力贡献", "tasks": "测试网／空投任务"}
SKILL_LABELS = {"beginner": "入门", "intermediate": "有一定操作经验", "advanced": "熟练维护"}


def _instant(value):
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_time must be a timezone-aware datetime or ISO timestamp")
    return value.astimezone(dt.timezone.utc)


def _fresh(value, current):
    if not value:
        return False
    age = current - _instant(value)
    return -CLOCK_SKEW <= age <= FRESHNESS


def _market_status(candidate, proof):
    facts = {field: set() for field in MARKET_FIELDS}
    scoped_absence = set()
    # Prior positive trading evidence is not erased merely by a recent heartbeat.
    if any(candidate["market"][field] == "yes" for field in ("cex_spot", "dex_spot", "premarket")):
        return None
    for item in candidate["evidence"]:
        if item["kind"] in ("official", "primary") and item["note"] and any(
                item["claims"].get(field) == "yes" for field in ("cex_spot", "dex_spot", "premarket")):
            return None
    for item in proof:
        for field, value in item["claims"].items():
            if value == "unknown":
                continue
            facts[field].add(value)
            if field in ("cex_spot", "dex_spot") and value == "no" and item["scope"]:
                scoped_absence.add(field)
    for field, values in facts.items():
        if len(values) > 1 or (values and candidate["market"][field] != "unknown" and candidate["market"][field] not in values):
            return None
    if facts["token_issued"] == {"no"}:
        return "unissued"
    if scoped_absence == {"cex_spot", "dex_spot"}:
        return "unlisted_supported"
    return None


def _revision(candidate):
    # Ignore check timestamps, ordering, UI summaries and user profile changes.
    # Resource/cost/participation/reward/market/evidence changes are substantive.
    content = {key: candidate[key] for key in ("id", "name", "category", "url", "requirements", "market", "participation", "reward_unit")}
    evidence = [{key: value for key, value in item.items() if key != "checked_at"}
                for item in candidate["evidence"] if item["kind"] in ("official", "primary")]
    content["evidence"] = sorted({json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in evidence})
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reward_description(unit):
    lowered = unit.lower()
    if lowered in ("points", "point", "积分", "credits", "credit"):
        return "奖励口径为积分／记分；不是已到账代币，兑换规则和价值未保证。"
    if lowered in ("unknown", "", "未知"):
        return "奖励形式尚未确认，不估算代币数量或收益。"
    if lowered in ("contribution", "贡献", "receipt"):
        return "当前按贡献或回执记录；不代表可兑换资产或保证收益。"
    return f"资料标注奖励单位为 {unit}；实际领取资格、数量与价值尚待确认。"


def build_request(candidate, hardware, profile, now_time=None):
    """Return a stable plan-review invitation, or None when evidence is insufficient.

    Unknown user budget/skill/availability may be asked in the invitation. Known
    incompatibility, unknown hardware requirements, unreviewed market claims,
    closed participation or evidence older than 48 hours cannot pass this rule.
    ``now_time`` controls the eligibility clock; domain validation still rejects
    malformed values. The caller alone persists, deduplicates and delivers it.
    """
    current = _instant(now_time) if now_time is not None else dt.datetime.now(dt.timezone.utc)
    item = normalize_candidate(candidate)
    profile = validate_profile(profile)
    if item["participation"] != "open" or not _fresh(item["checked_at"], current):
        return None
    proof = [entry for entry in item["evidence"] if entry["kind"] in ("official", "primary")
             and entry["note"] and _fresh(entry["checked_at"], current)]
    if not any(entry["kind"] == "official" for entry in proof):
        return None
    market_status = _market_status(item, proof)
    if market_status is None:
        return None
    requirements = item["requirements"]
    if any(requirements[field] is None for field in PROJECT_FIELDS) or not requirements["os"]:
        return None
    assessment = assess(item, hardware, profile)
    if any(check["status"] == "fail" or (check["field"] in HARDWARE_FIELDS and check["status"] != "pass")
           for check in assessment["checks"]):
        return None

    missing_messages = {"daily_hours": "尚需确认每天可运行的时长", "available_minutes": "尚需确认可投入的维护时间",
                        "skill_level": "尚需确认使用者的操作经验", "gpu_allowed": "尚需确认是否允许占用 GPU"}
    unknowns = [missing_messages[field] for field in assessment["missing"] if field in missing_messages]
    cost = requirements["estimated_daily_cost"]
    if cost is None:
        unknowns.append("项目日成本缺少可靠估算")
    if profile.get("max_daily_cost") is None:
        unknowns.append("尚需确认可接受的日成本上限")
    if cost is not None:
        unknowns.append("费用计价币种及覆盖范围尚待确认")
    unknowns.append("奖励资格、领取窗口和可交付结果仍需逐项核实")
    blockers = unknowns + ["项目执行配方、软件版本与成果验证步骤仍需审阅",
                           "确认意向后仍需确认资源、费用与交付对象的具体范围"]
    revision = _revision(item)
    evidence_sources = sorted(proof, key=lambda entry: (entry["kind"] != "official", entry["url"], entry["note"]))
    return {
        "id": f"request_{item['id']}_{revision[:16]}", "candidate_id": item["id"], "candidate_name": item["name"],
        "status": "pending", "created_at": current.isoformat(), "revision": revision,
        "reasons": ["已研究的项目资料在最近 48 小时内核验，且记录为开放参与",
                    "近期一手证据支持尚未发行" if market_status == "unissued" else "近期一手证据支持在所核查范围尚无现货交易",
                    "本机内存、磁盘、显存与系统达到已记录的最低要求",
                    "值得审阅参与计划；这不是收益保证或执行授权"],
        "plan": {
            "category_label": CATEGORIES[item["category"]],
            "resources": [{"name": label, "value": f"最低 {requirements[field]:g} GB"}
                          for field, label in (("min_ram_gb", "内存"), ("min_disk_gb", "磁盘"), ("min_vram_gb", "显存"))]
                         + [{"name": "系统", "value": " / ".join(requirements["os"])}],
            "runtime": f"每日约 {requirements['daily_hours']:g} 小时",
            "maintenance": f"每日约 {requirements['available_minutes']:g} 分钟",
            "required_skill": SKILL_LABELS[requirements["skill_level"]],
            "estimated_cost": "日成本尚待估算" if cost is None else f"来源估算值 {cost:g}／日（计价币种及费用范围待确认）",
            "reward": _reward_description(item["reward_unit"]),
            "delivery": "参与前约定可核验的贡献记录或任务回执；未确认奖励时不承诺资产到账。",
            "unknowns": unknowns,
            "execution_note": "确认意向不会启动任务；执行前仍需配方与具体范围确认。",
        },
        "evidence": evidence_sources, "blockers": blockers, "readiness": "plan_review_only",
    }
