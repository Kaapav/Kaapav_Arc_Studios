"""Small runtime guards for unattended local and cloud execution."""

import json
import os
import socket
import time
import uuid
from pathlib import Path


def pid_is_running(pid: int) -> bool:
    """Return whether a local process is alive without requiring extra packages."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, int(pid)
        )
        if not handle:
            # Access denied means the PID exists but belongs to a protected
            # process. Invalid parameter means the PID does not exist.
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class RunLock:
    """Prevent two schedulers from rendering/uploading at the same time."""

    def __init__(self, cfg, stale_after_seconds: int = 6 * 60 * 60):
        self.path = cfg.cache_dir() / "pipeline.lock"
        self.stale_after = stale_after_seconds
        self.token = uuid.uuid4().hex

    def _is_stale(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("host") == socket.gethostname():
                return not pid_is_running(int(data.get("pid", 0)))
            started = float(data.get("started_epoch", 0))
            return started <= 0 or (time.time() - started) > self.stale_after
        except Exception:
            try:
                return (time.time() - self.path.stat().st_mtime) > self.stale_after
            except OSError:
                return True

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = {
                    "token": self.token,
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "started_epoch": time.time(),
                }
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
                return self
            except FileExistsError:
                if attempt == 0 and self._is_stale():
                    self.path.unlink(missing_ok=True)
                    continue
                raise RuntimeError(
                    f"Another YT-Auto run is active ({self.path}). "
                    "Wait for it to finish; stale locks clear automatically after six hours."
                )
        raise RuntimeError("Could not acquire pipeline lock")

    def __exit__(self, exc_type, exc, tb):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except Exception:
            pass


def write_stage(job_dir: Path, stage: str, **details):
    """Atomically record the last completed stage for diagnosis and recovery."""
    path = Path(job_dir) / "status.json"
    payload = {
        "stage": stage,
        "updated_epoch": time.time(),
        **details,
    }
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
