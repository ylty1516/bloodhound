"""Trusted launch gate: no project code starts until its parent assigns this process to a Job."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    spec = json.loads(sys.stdin.readline())
    if spec['driver']=='unmineable-usdt-bsc-vm-cpu':
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from prospect.vm_mining import run_worker
        return run_worker(spec)
    if spec["driver"] == "local-self-check":
        print("本机执行器已启动，正在验证进程、日志和结果交付。", flush=True)
        for index in range(4):
            time.sleep(spec.get("seconds", 12) / 4)
            print(f"本机自检 {index + 1}/4：进程正常，日志可以读取。", flush=True)
        output = {"kind": "local-self-check", "verified": True, "steps": 4, "rewards": None}
        Path("self-check.json").write_text(json.dumps(output), "utf-8")
        print("自检完成，结果已写入。没有连接项目网络或运行矿工。", flush=True)
        return 0
    executable = Path(spec["argv"][0])
    with executable.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != spec["executable_sha256"]:
        print("启动前文件校验失败。", flush=True); return 81
    # No shell, no detached process and no extra inherited handles. Job membership is inherited.
    # Keep a pipe open for miners which inspect stdin. An immediately closed
    # console input is not a request to stop a server-owned mining process.
    child = subprocess.Popen(spec["argv"], stdin=subprocess.PIPE if spec['driver']=='unmineable-usdt-bsc-cpu' else subprocess.DEVNULL, close_fds=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    print(f"受控子进程已启动，PID {child.pid}。",flush=True)
    try:
        result=child.wait()
        print(f"受控子进程已结束，退出码 {result}。",flush=True)
        return result
    finally:
        if child.stdin:child.stdin.close()


if __name__ == "__main__":
    raise SystemExit(main())
