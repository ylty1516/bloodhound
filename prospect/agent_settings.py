"""Prospect-only model settings. Never edits host settings or reads credentials."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tomllib

from .store import _json

HOSTS = ("codex", "claude", "pi", "deepseek")
EFFORTS = {"codex": ("default", "minimal", "low", "medium", "high", "xhigh", "max"),
           "claude": ("default", "low", "medium", "high", "xhigh", "max")}
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}\Z")


def model_id(value):
    if not isinstance(value, str) or (value and not MODEL_ID.fullmatch(value)):
        raise ValueError("模型 ID 只能包含字母、数字及 . _ : / @ + -，最长160字符")
    if value.lower().startswith(("sk-", "http:", "https:")):
        raise ValueError("这里只填写模型 ID，不填写密钥或服务地址")
    return value


class AgentSettings:
    def __init__(self, store, home=None):
        self.store = store
        self.home = Path(home) if home else Path.home()
        self.codex_home = self.home / ".codex" if home else Path(os.environ.get("CODEX_HOME", str(self.home / ".codex")))

    def host_defaults(self):
        result = {h: {"model": None, "effort": None} for h in HOSTS}
        paths = [("codex", self.codex_home / "config.toml"), ("claude", self.home / ".claude/settings.json"),
                 ("pi", self.home / ".pi/agent/settings.json")]
        for host, path in paths:
            try:
                if path.stat().st_size > 1_000_000: continue
                raw = path.read_text("utf-8")
                data = tomllib.loads(raw) if host == "codex" else json.loads(raw)
                model = data.get("defaultModel" if host == "pi" else "model")
                effort = data.get({"codex": "model_reasoning_effort", "claude": "effortLevel", "pi": "defaultThinkingLevel"}[host])
                result[host] = {"model": model_id(model) if isinstance(model, str) else None,
                                "effort": effort if isinstance(effort, str) and effort in ("off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra") else None}
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return result

    def policy(self):
        saved = self.store.get_setting("agent_models")
        if saved is not None: return saved
        # The prior runner used low effort and no explicit model. Keep that policy
        # until the user saves a selection; expose unknown defaults honestly.
        return {"default_host": "any", "hosts": {h: {"model": "", "effort": "low"} for h in EFFORTS}}

    def catalog(self):
        models = []
        try:
            path = self.codex_home / "models_cache.json"
            if path.stat().st_size <= 2_000_000:
                for item in json.loads(path.read_text("utf-8")).get("models", []):
                    ident = model_id(item.get("slug", ""))
                    if not ident or item.get("visibility") == "hidden" or ident == "codex-auto-review": continue
                    efforts = [e.get("effort") for e in item.get("supported_reasoning_levels", []) if isinstance(e, dict) and e.get("effort") in EFFORTS["codex"]]
                    models.append({"id": ident, "efforts": efforts, "source": "local_host_catalog"})
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return models[:50]

    def view(self):
        return {"policy": self.policy(), "fingerprint": self.fingerprint(), "host_defaults": self.host_defaults(), "catalog": {"codex": self.catalog()},
                "efforts": {k: list(v) for k, v in EFFORTS.items()}, "editable_hosts": list(EFFORTS),
                "scope": "next_prospect_checks", "host_session_note": "pi / DeepSeek 任务在已运行宿主中领取，模型由该会话控制，网页不能替它更换。"}

    def save(self, value):
        if not isinstance(value, dict) or set(value) != {"default_host", "hosts"} or value["default_host"] not in (*HOSTS, "deepseek_api", "any"):
            raise ValueError("Invalid Agent model settings")
        if not isinstance(value["hosts"], dict) or set(value["hosts"]) != set(EFFORTS):
            raise ValueError("Only native Codex / Claude runs can be configured here")
        clean = {"default_host": value["default_host"], "hosts": {}}
        catalog = {m["id"]: m for m in self.catalog()}
        for host, item in value["hosts"].items():
            if not isinstance(item, dict) or set(item) != {"model", "effort"} or item["effort"] not in EFFORTS[host]:
                raise ValueError("不支持的思考强度")
            model = model_id(item["model"].strip() if isinstance(item["model"], str) else item["model"])
            if host == "codex" and model in catalog and item["effort"] != "default" and catalog[model]["efforts"] and item["effort"] not in catalog[model]["efforts"]:
                raise ValueError("本机模型目录未声明支持所选思考强度")
            clean["hosts"][host] = {"model": model, "effort": item["effort"]}
        self.store.set_setting("agent_models", clean)
        return self.view()

    def snapshot(self, host, method, policy=None):
        selected = (policy or self.policy())["hosts"].get(host, {}) if method == "native_cli" else {}
        return {"host": host, "method": method, "requested_model": selected.get("model") or None,
                "requested_effort": selected.get("effort") if selected.get("effort") != "default" else None,
                "model_source": "prospect_setting" if selected.get("model") else "host_default" if method == "native_cli" else "host_session",
                "observed_models": [], "actual_effort": None}

    def fingerprint(self, policy=None):
        return hashlib.sha256(_json(policy or self.policy()).encode()).hexdigest()


def observed_models(event, host):
    """Only allowlisted model IDs; do not persist system prompts or transcripts."""
    values = []
    if host == "claude":
        if event.get("type") == "system" and event.get("subtype") == "init": values.append(event.get("model"))
        if isinstance(event.get("message"), dict): values.append(event["message"].get("model"))
        if event.get("type") == "result" and isinstance(event.get("modelUsage"), dict): values.extend(event["modelUsage"].keys())
    elif event.get("type") in ("thread.started", "turn.started", "turn.completed"):
        values.append(event.get("model"))
    output = []
    for value in values:
        try:
            if value: output.append(model_id(value))
        except ValueError:
            pass
    return sorted(set(output))[:8]
