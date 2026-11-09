"""SQLite persistence; deterministic queues never invoke a model or execute a project."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from .domain import normalize_candidate, now, validate_profile, _number


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Value must be finite JSON data") from exc


def _revision(candidate):
    content = {k: v for k, v in candidate.items() if k not in ("checked_at", "classification", "confidence")}
    content["evidence"] = sorted(({k: v for k, v in item.items() if k != "checked_at"} for item in candidate["evidence"]), key=_json)
    return hashlib.sha256(_json(content).encode()).hexdigest()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE,
                    revision TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scans (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS run_annotations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS participation_requests (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS launch_watch (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research (
                    id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, revision TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT,
                    UNIQUE(candidate_id, revision)
                );
            """)

    @contextmanager
    def _connection(self, write=False):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _event(connection, kind, payload):
        event = {"id": uuid.uuid4().hex, "kind": kind, "at": now(), "payload": payload}
        connection.execute("INSERT INTO events(payload) VALUES (?)", (_json(event),))
        return event

    def upsert_candidate(self, data):
        candidate = normalize_candidate(data)
        revision = _revision(candidate)
        with self._connection(write=True) as connection:
            old = connection.execute("SELECT revision,payload FROM candidates WHERE id=?", (candidate["id"],)).fetchone()
            if old:
                previous = json.loads(old["payload"])
                if previous["checked_at"] and (not candidate["checked_at"] or candidate["checked_at"] < previous["checked_at"]):
                    return {"id": candidate["id"], "changed": False}
            changed = old is None or old["revision"] != revision
            if old and not changed:
                # A discovery heartbeat must not erase the evidence added by host review.
                candidate = normalize_candidate(previous | {"checked_at": candidate["checked_at"]})
            connection.execute("""INSERT INTO candidates VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,updated_at=excluded.updated_at""",
                (candidate["id"], candidate["identity_key"], revision, _json(candidate), now()))
            if changed:
                connection.execute("UPDATE research SET status='superseded' WHERE candidate_id=? AND status='pending' AND revision<>?", (candidate["id"], revision))
                job = {"id": uuid.uuid4().hex, "candidate_id": candidate["id"], "revision": revision,
                       "status": "pending", "at": now(), "model_execution": "unavailable"}
                inserted = connection.execute("INSERT OR IGNORE INTO research VALUES (?,?,?,?,?,NULL)",
                                              (job["id"], candidate["id"], revision, "pending", _json(job))).rowcount
                if inserted:
                    self._event(connection, "research_requested", {"candidate_id": candidate["id"], "revision": revision, "research_id": job["id"]})
                else:
                    connection.execute("UPDATE research SET status='pending' WHERE candidate_id=? AND revision=? AND status='superseded'", (candidate["id"], revision))
        return {"id": candidate["id"], "changed": changed}

    def candidates(self):
        with self._connection() as connection:
            return [normalize_candidate(json.loads(row["payload"])) for row in connection.execute("SELECT payload FROM candidates ORDER BY updated_at DESC,id")]

    def get_candidate(self, ident):
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM candidates WHERE id=?", (ident,)).fetchone()
            return normalize_candidate(json.loads(row[0])) if row else None

    def get_setting(self, key, default=None):
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        if not isinstance(key, str) or not key or len(key) > 120:
            raise ValueError("Invalid setting key")
        if key in ("api_key", "private_key", "seed_phrase", "password"):
            raise ValueError("Secrets do not belong in the settings database")
        if key == "profile":
            value = validate_profile(value)
        if key in ("policy", "host_usage"):
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object")
            for name, amount in value.items():
                if any(term in name for term in ("budget", "limit", "cost", "tokens", "calls")):
                    _number(amount, name)
                    if any(term in name for term in ("token", "calls")) and not isinstance(amount, int):
                        raise ValueError(f"{name} must be an integer")
        payload = _json(value)
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", (key, payload))

    def save_hardware(self, data):
        if not isinstance(data, dict):
            raise ValueError("Hardware must be an object")
        self.set_setting("hardware", data)

    def hardware(self):
        return self.get_setting("hardware", {})

    def save_profile(self, data):
        clean = validate_profile(data)
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT payload FROM settings WHERE key='profile'").fetchone()
            merged = (json.loads(row[0]) if row else {}) | clean
            connection.execute("INSERT INTO settings VALUES ('profile',?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", (_json(merged),))

    def profile(self):
        return self.get_setting("profile", {})

    def record_scan(self, data):
        if not isinstance(data, dict):
            raise ValueError("Scan must be an object")
        entry = {"at": now()} | data
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO scans(payload) VALUES (?)", (_json(entry),))

    @staticmethod
    def _limit(limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Limit must be an integer from 1 to 1000")
        return limit

    def scans(self, limit=50):
        with self._connection() as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM scans ORDER BY sequence DESC LIMIT ?", (self._limit(limit),))]

    def add_run(self, data):
        if not isinstance(data, dict):
            raise ValueError("Run must be an object")
        entry = {"id": uuid.uuid4().hex, "at": now()} | data
        if not isinstance(entry["id"], str) or not entry["id"]:
            raise ValueError("Run id required")
        with self._connection(write=True) as connection:
            old = connection.execute("SELECT payload FROM runs WHERE id=?", (entry["id"],)).fetchone()
            if old:
                existing = json.loads(old[0])
                if any(existing.get(key) != value for key, value in data.items()):
                    raise ValueError("Run id already exists with a different result")
                return existing
            connection.execute("INSERT INTO runs VALUES (?,?)", (entry["id"], _json(entry)))
        return entry

    def runs(self):
        with self._connection() as connection:
            return [json.loads(row[0]) | (json.loads(row[1]) if row[1] else {}) for row in connection.execute(
                "SELECT r.payload,a.payload FROM runs r LEFT JOIN run_annotations a ON r.id=a.id ORDER BY r.rowid DESC")]

    def annotate_validation_run(self, ident, reason):
        """Retain the raw historical result; provenance is separate, never guessed from status."""
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT payload FROM runs WHERE id=?", (ident,)).fetchone()
            if not row or json.loads(row[0]).get("mode") != "simulation":
                raise ValueError("Only an identified simulation may be annotated")
            annotation = {"origin": "validation", "origin_note": reason}
            connection.execute("INSERT INTO run_annotations VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (ident, _json(annotation)))

    def sync_participation_requests(self, proposals):
        """One durable request per material revision; polling never repeats notifications."""
        with self._connection(write=True) as connection:
            rows = {row[0]: json.loads(row[1]) for row in connection.execute("SELECT id,payload FROM participation_requests")}
            active = {p["id"] for p in proposals}
            for ident, previous in rows.items():
                if ident not in active and previous["status"] in ("pending", "interested"):
                    previous.update(status_before_stale=previous["status"], status="stale", stale_at=now())
                    connection.execute("UPDATE participation_requests SET payload=? WHERE id=?", (_json(previous), ident))
            for proposal in proposals:
                ident = proposal["id"]
                previous = rows.get(ident)
                if previous:
                    # Revalidation restores intent without sending another new-request event.
                    # Dismissal survives refresh and restart.
                    item = previous | {k: v for k, v in proposal.items() if k not in ("status", "created_at")}
                    if previous["status"] == "stale":
                        item["status"] = previous.get("status_before_stale", "pending")
                        item["revalidated_at"] = now()
                        self._event(connection, "participation_revalidated", {"request_id": ident})
                    connection.execute("UPDATE participation_requests SET payload=? WHERE id=?", (_json(item), ident))
                else:
                    item = proposal | {"status": "pending", "execution_authorized": False}
                    connection.execute("INSERT INTO participation_requests VALUES (?,?)", (ident, _json(item)))
                    self._event(connection, "participation_requested", {"request_id": ident, "candidate_id": item["candidate_id"]})
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM participation_requests ORDER BY rowid DESC")]

    def decide_participation(self, ident, decision):
        if decision not in ("interested", "dismissed"):
            raise ValueError("decision must be interested or dismissed")
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT payload FROM participation_requests WHERE id=?", (ident,)).fetchone()
            if not row: raise ValueError("Unknown participation request")
            item = json.loads(row[0])
            if item["status"] == decision: return item
            if item["status"] != "pending": raise ValueError("Request is no longer pending; review the current plan")
            item.update(status=decision, decided_at=now(), execution_authorized=False)
            connection.execute("UPDATE participation_requests SET payload=? WHERE id=?", (_json(item), ident))
            self._event(connection, "participation_decision", {"request_id": ident, "decision": decision, "execution_authorized": False})
            return item

    def add_event(self, kind, payload):
        if not isinstance(kind, str) or not kind or len(kind) > 120:
            raise ValueError("Invalid event kind")
        with self._connection(write=True) as connection:
            return self._event(connection, kind, payload)

    def events(self, limit=50):
        with self._connection() as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM events ORDER BY sequence DESC LIMIT ?", (self._limit(limit),))]

    def research_jobs(self):
        with self._connection() as connection:
            rows = connection.execute("SELECT payload,status,result FROM research ORDER BY rowid DESC")
            return [json.loads(row["payload"]) | {"status": row["status"], "result": json.loads(row["result"]) if row["result"] else None} for row in rows]

    def reviewed_candidates(self):
        with self._connection() as connection:
            return [normalize_candidate(json.loads(row[0])) for row in connection.execute(
                "SELECT c.payload,r.result FROM candidates c JOIN research r ON r.candidate_id=c.id AND r.revision=c.revision WHERE r.status='resolved'")
                if (json.loads(row[1]) if row[1] else {}).get("agent_verdict") != "unsuitable"]

    def resolve_research(self, ident, result):
        if not isinstance(result, dict):
            raise ValueError("Research result must be an object")
        patch = result.get("candidate", result)
        if not isinstance(patch, dict):
            raise ValueError("Research candidate patch must be an object")
        if any(key in patch for key in ("approved", "authorized", "live_execution_allowed", "execute")):
            raise ValueError("Research cannot grant execution permission")
        with self._connection(write=True) as connection:
            job = connection.execute("SELECT * FROM research WHERE id=?", (ident,)).fetchone()
            if not job:
                raise ValueError("Unknown research job")
            if job["status"] == "resolved" and not patch:
                return json.loads(job["result"])
            row = connection.execute("SELECT payload,revision FROM candidates WHERE id=?", (job["candidate_id"],)).fetchone()
            if not row or row["revision"] != job["revision"]:
                raise ValueError("Research revision is stale; review the current candidate")
            original = json.loads(row["payload"])
            candidate = normalize_candidate(original | patch)
            if candidate["id"] != job["candidate_id"]:
                raise ValueError("Research cannot change project identity")
            if original["checked_at"] and (not candidate["checked_at"] or candidate["checked_at"] < original["checked_at"]):
                raise ValueError("Research cannot replace a newer observation with an older one")
            evidence = candidate["evidence"]
            if not evidence or not candidate["checked_at"] or not any(e["kind"] in ("primary", "official") and e["checked_at"] and e["note"] for e in evidence):
                raise ValueError("Research requires dated primary evidence and checked_at")
            import datetime as dt
            current = dt.datetime.now(dt.timezone.utc)
            dated = [e for e in evidence if e["kind"] in ("primary", "official") and e["checked_at"] and e["note"]]
            if not any(current - dt.datetime.fromisoformat(e["checked_at"]) <= dt.timedelta(days=7) for e in dated):
                raise ValueError("Research primary evidence is stale")
            reviewed = {"id": ident, "candidate_id": candidate["id"], "status": "resolved", "at": now(),
                        "candidate": candidate, "live_execution_allowed": False, "review_method": "host_provided_evidence"}
            if result.get("report") is not None:
                from .agent_checks import validate_report, HOSTS
                from .domain import assess
                host=result.get("host")
                if host not in HOSTS: raise ValueError("Host review needs a known host identity")
                reviewed["report"]=validate_report(result["report"],assess(candidate,self.hardware(),self.profile()))
                reviewed["agent_verdict"]=reviewed["report"]["verdict"]
                reviewed["host"]=host
            # A human/host review closes this queue entry; it never recursively enqueues itself.
            connection.execute("UPDATE candidates SET payload=?,updated_at=? WHERE id=?", (_json(candidate), now(), candidate["id"]))
            connection.execute("UPDATE research SET status='resolved',result=? WHERE id=?", (_json(reviewed), ident))
            self._event(connection, "research_updated" if job["status"] == "resolved" else "research_resolved",
                        {"research_id": ident, "candidate_id": candidate["id"], "live_execution_allowed": False})
            return reviewed

    def usage(self):
        with self._connection() as connection:
            pending = connection.execute("SELECT count(*) FROM research WHERE status='pending'").fetchone()[0]
        return {"background_model_calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,
                "host_usage": self.get_setting("host_usage", "unknown"), "developer_usage": "unknown",
                "model_execution": "unavailable", "research_pending": pending}
