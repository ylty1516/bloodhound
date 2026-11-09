"""Windows process-tree limits. Resource containment, not a security sandbox."""
import ctypes
from ctypes import wintypes as W
import os


class Basic(ctypes.Structure):
    _fields_ = [("user", ctypes.c_longlong), ("job_user", ctypes.c_longlong),
                ("flags", W.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                ("active", W.DWORD), ("affinity", ctypes.c_size_t), ("priority", W.DWORD), ("scheduling", W.DWORD)]


class Extended(ctypes.Structure):
    _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


class Cpu(ctypes.Structure):
    _fields_ = [("flags", W.DWORD), ("rate", W.DWORD)]


class Job:
    def __init__(self, cpu_percent, memory_mb):
        if os.name != "nt":
            raise ValueError("此版本的真实执行器需要 Windows Job Objects；其他系统暂不启动项目。")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, W.LPCWSTR], W.HANDLE),
            "SetInformationJobObject": ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD], W.BOOL),
            "QueryInformationJobObject": ([W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.c_void_p], W.BOOL),
            "AssignProcessToJobObject": ([W.HANDLE, W.HANDLE], W.BOOL),
            "TerminateJobObject": ([W.HANDLE, W.UINT], W.BOOL),
            "CloseHandle": ([W.HANDLE], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            f = getattr(self.api, name); f.argtypes = args; f.restype = result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            limit = Extended()
            # KILL_ON_JOB_CLOSE, JOB_MEMORY, ACTIVE_PROCESS. Children inherit membership.
            limit.basic.flags = 0x2000 | 0x200 | 0x8
            limit.basic.active = 8
            limit.job_memory = memory_mb * 1024 * 1024
            self._set(9, limit)
            self._set(15, Cpu(0x1 | 0x4, cpu_percent * 100))
        except BaseException:
            self.close(); raise

    def _set(self, kind, value):
        if not self.api.SetInformationJobObject(self.handle, kind, ctypes.byref(value), ctypes.sizeof(value)):
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, W.HANDLE(int(process._handle))):
            raise ctypes.WinError(ctypes.get_last_error())

    def limits(self):
        limit, cpu = Extended(), Cpu()
        for kind, value in ((9, limit), (15, cpu)):
            if not self.api.QueryInformationJobObject(self.handle, kind, ctypes.byref(value), ctypes.sizeof(value), None):
                raise ctypes.WinError(ctypes.get_last_error())
        return {"cpu_percent": cpu.rate // 100, "memory_mb": limit.job_memory // (1024 * 1024),
                "kill_on_close": bool(limit.basic.flags & 0x2000), "peak_memory_mb": round(limit.peak_job / 1048576, 2)}

    def terminate(self):
        if self.handle: self.api.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle = None


def idle_seconds():
    class LastInput(ctypes.Structure):
        _fields_ = [("size", W.UINT), ("tick", W.DWORD)]
    value = LastInput(); value.size = ctypes.sizeof(value)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(value)):
        raise OSError("无法读取用户空闲状态")
    return ((ctypes.windll.kernel32.GetTickCount() & 0xffffffff) - value.tick & 0xffffffff) / 1000
