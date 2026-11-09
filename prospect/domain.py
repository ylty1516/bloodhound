"""Pure validation, conservative classification and explicitly simulated plans."""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import math
import urllib.parse

MARKET_FIELDS = ("token_issued", "tge", "mainnet", "transferable", "cex_spot", "dex_spot", "premarket")
SKILLS = {"beginner": 0, "intermediate": 1, "advanced": 2}
PROFILE_FIELDS = {"electricity_price", "daily_hours", "cpu_limit_pct", "gpu_allowed", "max_daily_cost", "skill_level", "available_minutes"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _text(value, name, limit=2000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{name} must be a string of at most {limit} characters")
    return value.strip()


def _number(value, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} exceeds {maximum}")
    return value


def _time(value, name):
    if value in (None, ""):
        return None
    value = _text(value, name, 80)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    parsed = parsed.astimezone(dt.timezone.utc)
    if parsed > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise ValueError(f"{name} cannot be in the future")
    return parsed.isoformat()


def _url(value):
    value = _text(value, "url", 4096)
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL") from exc
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or any(ord(c) < 33 for c in value):
        raise ValueError("Public HTTPS URL without credentials required")
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("Local evidence URL is not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private evidence URL is not allowed")
    netloc = f"[{host}]" if ":" in host else host
    if port and port != 443:
        netloc += f":{port}"
    return urllib.parse.urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def validate_profile(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) - PROFILE_FIELDS:
        raise ValueError("Unsupported profile fields")
    result = {}
    limits = {"daily_hours": 24, "cpu_limit_pct": 100, "available_minutes": 1440}
    for key, value in data.items():
        if value is None:
            result[key] = None
        elif key == "gpu_allowed":
            if type(value) is not bool:
                raise ValueError("gpu_allowed must be boolean")
            result[key] = value
        elif key == "skill_level":
            if not isinstance(value, str) or value not in SKILLS:
                raise ValueError("Unknown skill level")
            result[key] = value
        else:
            result[key] = _number(value, key, limits.get(key))
    return result


def _classification(market, evidence):
    current = dt.datetime.now(dt.timezone.utc)
    supported = {key: set() for key in MARKET_FIELDS}
    scoped_no = set()
    for item in evidence:
        checked = item["checked_at"]
        if item["kind"] not in ("official", "primary") or not item["note"] or not checked:
            continue
        if current - dt.datetime.fromisoformat(checked) > dt.timedelta(days=7):
            continue
        for key, value in item["claims"].items():
            if value != "unknown":
                supported[key].add(value)
                if key in ("cex_spot", "dex_spot") and value == "no" and item["scope"]:
                    scoped_no.add(key)
    if any(len(values) > 1 or (values and market[key] != "unknown" and market[key] not in values)
           for key, values in supported.items()):
        return "conflict", "low"
    known = {key: next(iter(values)) if values else "unknown" for key, values in supported.items()}
    if known["cex_spot"] == "yes" or known["dex_spot"] == "yes":
        return "listed", "high"
    if known["premarket"] == "yes":
        return "premarket", "medium"
    if known["token_issued"] == "no":
        return "unissued", "medium"
    if scoped_no == {"cex_spot", "dex_spot"}:
        return "unlisted_supported", "medium"
    return "unknown", "low"


def normalize_candidate(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Candidate must be an object")
    name = _text(data.get("name", ""), "name", 160)
    if not name:
        raise ValueError("Candidate name required")
    category = data.get("category")
    if category not in ("pow", "node", "tasks"):
        raise ValueError("category must be pow, node or tasks")
    url = _url(data.get("url", ""))
    identity = _text(data.get("identity_key", url), "identity_key", 512)
    if not identity:
        raise ValueError("identity_key cannot be empty")
    supplied_market = data.get("market", {})
    if not isinstance(supplied_market, dict) or set(supplied_market) - set(MARKET_FIELDS):
        raise ValueError("Invalid market fields")
    market = {key: supplied_market.get(key, "unknown") for key in MARKET_FIELDS}
    if any(value not in ("yes", "no", "unknown") for value in market.values()):
        raise ValueError("Market facts must be yes, no or unknown")
    raw_evidence = data.get("evidence", [])
    if not isinstance(raw_evidence, list) or len(raw_evidence) > 40:
        raise ValueError("Evidence must be a list of at most 40 items")
    evidence = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            raise ValueError("Evidence item must be an object")
        claims = item.get("claims", {})
        if not isinstance(claims, dict) or set(claims) - set(MARKET_FIELDS) or any(v not in ("yes", "no", "unknown") for v in claims.values()):
            raise ValueError("Invalid evidence claims")
        evidence.append({"url": _url(item.get("url", "")), "kind": _text(item.get("kind", "discovery"), "kind", 40),
                         "note": _text(item.get("note", ""), "note"), "checked_at": _time(item.get("checked_at"), "evidence.checked_at"),
                         "claims": dict(claims), "scope": _text(item.get("scope", ""), "scope", 500)})
    raw = data.get("requirements", {})
    if not isinstance(raw, dict):
        raise ValueError("requirements must be an object")
    requirements = {}
    for key in ("min_ram_gb", "min_disk_gb", "min_vram_gb", "daily_hours", "available_minutes", "estimated_daily_cost"):
        value = raw.get(key)
        requirements[key] = None if value is None else _number(value, key, {"daily_hours": 24, "available_minutes": 1440}.get(key))
    systems = raw.get("os", [])
    if isinstance(systems, str):
        systems = [systems]
    if not isinstance(systems, list) or len(systems) > 12:
        raise ValueError("requirements.os must be a list")
    requirements["os"] = sorted({_text(value, "os", 60).lower() for value in systems})
    skill = raw.get("skill_level")
    if skill is not None and (not isinstance(skill, str) or skill not in SKILLS):
        raise ValueError("Invalid required skill level")
    requirements["skill_level"] = skill
    participation = data.get("participation", "unknown")
    if participation not in ("open", "closed", "unknown"):
        raise ValueError("Invalid participation status")
    classification, confidence = _classification(market, evidence)
    return {"id": hashlib.sha256(identity.encode()).hexdigest()[:24], "identity_key": identity,
            "name": name, "category": category, "url": url, "summary": _text(data.get("summary", ""), "summary", 6000),
            "evidence": evidence, "market": market, "requirements": requirements,
            "reward_unit": _text(data.get("reward_unit", "unknown"), "reward_unit", 80),
            "participation": participation, "checked_at": _time(data.get("checked_at"), "checked_at"),
            "classification": classification, "confidence": confidence}


def assess(candidate: dict, hardware: dict, profile: dict) -> dict:
    candidate = normalize_candidate(candidate)
    profile = validate_profile(profile)
    if not isinstance(hardware, dict):
        raise ValueError("Hardware must be an object")
    requirements = candidate["requirements"]
    checks = []

    def check(field, required, actual, condition, message):
        status = "unknown" if required is None or actual is None else ("pass" if condition else "fail")
        checks.append({"field": field, "status": status, "required": required, "actual": actual, "message": message})

    for key, actual_key in (("min_ram_gb", "ram_gb"), ("min_disk_gb", "disk_free_gb"), ("min_vram_gb", "vram_gb")):
        required, actual = requirements[key], hardware.get(actual_key)
        if actual is not None:
            try:
                actual = _number(actual, actual_key)
            except ValueError:
                actual = None
        if required == 0:
            actual = 0 if actual is None else actual
        check(key, required, actual, required is not None and actual is not None and actual >= required, f"{actual_key} 与项目最低要求对照")
    systems = requirements["os"] or None
    system = hardware.get("os")
    check("os", systems, system, bool(systems and isinstance(system, str) and system.lower() in systems), "核对操作系统；缺失要求保持未知")
    check("participation", "open", candidate["participation"] if candidate["participation"] != "unknown" else None,
          candidate["participation"] == "open", "参与窗口必须明确开放")
    for key in ("daily_hours", "available_minutes"):
        required, actual = requirements[key], profile.get(key)
        check(key, required, actual, required is not None and actual is not None and actual >= required, "用户可投入时间与项目要求对照")
    skill, actual_skill = requirements["skill_level"], profile.get("skill_level")
    check("skill_level", skill, actual_skill, skill in SKILLS and actual_skill in SKILLS and SKILLS[actual_skill] >= SKILLS[skill], "技术能力由用户填写，不从硬件推断")
    if requirements["min_vram_gb"] and requirements["min_vram_gb"] > 0:
        check("gpu_allowed", True, profile.get("gpu_allowed"), profile.get("gpu_allowed") is True, "使用 GPU 须符合用户资源偏好")
    cost, budget = requirements["estimated_daily_cost"], profile.get("max_daily_cost")
    check("daily_cost", cost, budget, cost is not None and budget is not None and cost <= budget, "成本缺失时不能认定符合预算；无代币收益预测")
    if profile.get("cpu_limit_pct") == 0 and candidate["category"] in ("pow", "node"):
        check("cpu_limit_pct", 1, 0, False, "用户 CPU 配额为零")
    statuses = {item["status"] for item in checks}
    status = "incompatible" if "fail" in statuses else "unknown" if "unknown" in statuses else "compatible"
    return {"status": status, "checks": checks, "reasons": [item["message"] for item in checks if item["status"] != "pass"],
            "missing": [item["field"] for item in checks if item["status"] == "unknown"],
            "estimated_daily_cost": cost, "live_execution_allowed": False}


def simulate(candidate: dict, hardware: dict, profile: dict) -> dict:
    candidate = normalize_candidate(candidate)
    assessment = assess(candidate, hardware, profile)
    blocked = assessment["status"] != "compatible"
    steps = [{"name": "preflight", "status": "blocked" if blocked else "mock", "detail": "模拟前置检查；未知或不兼容条件阻止执行计划通过"}]
    for name, label in (("prepare", "准备依赖"), ("run", "运行项目"), ("verify", "验证贡献"), ("deliver", "交付成果")):
        steps.append({"name": name, "status": "blocked" if blocked else "mock", "detail": f"模拟：{label}，未实际执行"})
    return {"id": hashlib.sha256((candidate["id"] + now()).encode()).hexdigest()[:24], "mode": "simulation",
            "status": "blocked" if blocked else "simulated", "candidate_id": candidate["id"], "at": now(),
            "assessment": assessment, "steps": steps, "side_effects": False,
            "rewards": {"real": False, "amount": None, "unit": candidate["reward_unit"]}, "live_execution_allowed": False}
