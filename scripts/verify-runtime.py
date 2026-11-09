"""Real process tests in isolated LOCALAPPDATA state; never starts observation or a model."""
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prospect.cli import request


def cli(directory, port, *args, check=True):
    start = time.perf_counter()
    result = subprocess.run([sys.executable, "-m", "prospect", "--data-dir", str(directory),
                             "--port", str(port), *args], cwd=ROOT,
                            capture_output=True, encoding="utf-8", timeout=20)
    duration = round((time.perf_counter() - start) * 1000, 1)
    if check and result.returncode:
        raise AssertionError(result.stderr[-800:])
    return result, duration


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_down(port):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(.05)
    raise AssertionError("Owned test service did not stop")


def main():
    runtime_parent = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Prospect" / "qa"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "scope": "isolated real processes; no source requests/model calls/project execution",
              "targets": {"hot_p95_ms": 500, "cold_max_ms": 2000}}
    with tempfile.TemporaryDirectory(prefix="lifecycle-", dir=runtime_parent) as folder:
        directory, port = Path(folder), free_port()
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                cold = list(pool.map(lambda _: cli(directory, port, "ensure"), range(8)))
            pids = {json.loads(r.stdout)["pid"] for r, _ in cold}
            assert len(pids) == 1, pids
            pid = pids.pop()
            report["cold_concurrent_clients"] = 8
            report["unique_service_pids"] = 1
            report["cold_ms"] = [ms for _, ms in cold]
            hot = [cli(directory, port, "ensure")[1] for _ in range(20)]
            p95 = sorted(hot)[18]
            report["hot_samples"] = 20
            report["hot_p95_ms"] = p95
            report["hot_target_met"] = p95 <= 500
            report["cold_target_met"] = max(report["cold_ms"]) <= 2000
            request(directory, port, "/api/profile", {"daily_hours": 1, "gpu_allowed": False})
            old_token = json.loads((directory / "control.json").read_text("utf-8"))["token"]
            collision, _ = cli(directory, free_port(), "ensure", check=False)
            assert collision.returncode != 0 and "already served" in collision.stdout, collision.stdout
            report["second_port_rejected"] = True
            other = directory / "other"
            conflict, _ = cli(other, port, "ensure", check=False)
            assert conflict.returncode != 0
            report["same_port_other_directory_rejected"] = True
            # Only terminate the PID returned by this test's isolated service.
            current = json.loads((directory / "control.json").read_text("utf-8"))
            assert current["pid"] == pid and current["port"] == port
            os.kill(pid, signal.SIGTERM)
            wait_down(port)
            restarted, elapsed = cli(directory, port, "ensure")
            assert json.loads(restarted.stdout)["pid"] != pid
            state = request(directory, port)
            assert state["profile"]["daily_hours"] == 1 and state["profile"]["gpu_allowed"] is False
            assert state["observation"]["status"] == "not_started"
            assert state["usage"]["background_model_calls"] == 0
            new_token = json.loads((directory / "control.json").read_text("utf-8"))["token"]
            assert old_token != new_token
            report.update(crash_restart_ms=elapsed, profile_preserved=True, stale_lock_recovered=True,
                          private_token_rotated=True, observation_not_started=True, background_model_calls=0)
        finally:
            try:
                request(directory, port, "/api/shutdown", {}, timeout=3)
                wait_down(port)
            except (OSError, RuntimeError):
                pass
            time.sleep(.3)
    (ROOT / "evidence" / "runtime-lifecycle.json").write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
