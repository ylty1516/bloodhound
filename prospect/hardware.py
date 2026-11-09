"""Read-only hardware inventory. Unknown measurements stay unknown."""
from __future__ import annotations
import ctypes
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def inventory(path: Path | None = None) -> dict:
    result = {"os": platform.system().lower(), "os_version": platform.version(),
              "arch": platform.machine(), "cpu_name": platform.processor() or "unknown",
              "cpu_logical": os.cpu_count(), "ram_gb": None, "vram_gb": None,
              "disk_free_gb": round(shutil.disk_usage(path or Path.cwd()).free / 1024**3, 2),
              "gpus": [], "storage_path": str(path or Path.cwd()), "python_version": platform.python_version(),
              "temperature_c": None, "power_w": None,
              "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("total_phys", "avail_phys", "total_page",
                                                  "avail_page", "total_virtual", "avail_virtual", "extended")]
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result["ram_gb"] = round(memory.total_phys / 1024**3, 2)
        try:
            command = "@{cpu=(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name); gpus=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion)} | ConvertTo-Json -Compress"
            proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                  capture_output=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
            if proc.returncode == 0 and proc.stdout.strip():
                info = json.loads(proc.stdout.decode("utf-8-sig", errors="replace"))
                result["gpus"] = info.get("gpus", [])
                result["cpu_name"] = info.get("cpu") or result["cpu_name"]
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    else:
        try:
            result["ram_gb"] = round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3, 2)
        except (OSError, ValueError, AttributeError):
            pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            proc = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=5,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            gpus = []
            for line in proc.stdout.splitlines():
                name, memory, driver = [x.strip() for x in line.rsplit(",", 2)]
                gpus.append({"name": name, "vram_gb": round(float(memory) / 1024, 2), "driver": driver})
            if gpus:
                result["gpus"] = gpus
                result["vram_gb"] = max(g["vram_gb"] for g in gpus)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return result
