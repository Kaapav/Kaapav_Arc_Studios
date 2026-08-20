#!/usr/bin/env python3
"""KAAPAV ARC zero-touch studio supervisor.

The supervisor owns successful execution, while the controller owns production
state.  It verifies the runtime, starts one bounded controller cycle, confirms
the resulting state, and leaves machine-readable recovery evidence.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "analytics" / "supervisor_state.json"
AUTOPILOT_STATE = ROOT / "analytics" / "autopilot_state.json"
INVENTORY_PATH = ROOT / "analytics" / "studio_inventory.json"
PRODUCTION_QUEUE = ROOT / "analytics" / "production_queue.json"
CREATIVE_QUEUE = ROOT / "analytics" / "creative_queue.json"
PAUSE_PATH = ROOT / "analytics" / "PAUSE_AUTOPILOT"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def dependency_health() -> dict[str, Any]:
    free = shutil.disk_usage(ROOT).free
    checks = {
        "python": Path(sys.executable).exists(),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "controller": (ROOT / "studio_autopilot.py").exists(),
        "config": (ROOT / "config.story.yaml").exists(),
        "master_plan": (ROOT / "content" / "studio_master_release_plan.json").exists(),
        "free_disk_gb": round(free / (1024 ** 3), 2),
    }
    checks["healthy"] = all(value for key, value in checks.items() if key != "free_disk_gb") and checks["free_disk_gb"] >= 8
    return checks


def queue_summary(path: Path) -> dict[str, int]:
    tasks = _read(path).get("tasks") or []
    return {
        "queued": sum(task.get("state") == "queued" for task in tasks),
        "in_progress": sum(task.get("state") == "in_progress" for task in tasks),
        "blocked": sum(task.get("state") in {"blocked", "quarantined"} for task in tasks),
        "total": len(tasks),
    }


def run_controller(args) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable, "-u", str(ROOT / "studio_autopilot.py"), "--once",
        "--render-limit", str(args.render_limit), "--upload-limit", str(args.upload_limit),
    ]
    if args.no_network:
        command.append("--no-network")
    if args.no_google:
        command.append("--no-google")
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True,
        timeout=args.timeout_minutes * 60,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-limit", type=int, default=1)
    parser.add_argument("--upload-limit", type=int, default=4)
    parser.add_argument("--timeout-minutes", type=int, default=170)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--no-google", action="store_true")
    args = parser.parse_args()
    state: dict[str, Any] = {
        "schema_version": 1,
        "started_at": _now(),
        "status": "running",
        "normal_manual_actions": 0,
        "dependencies": dependency_health(),
    }
    _write(STATE_PATH, state)
    if PAUSE_PATH.exists():
        state.update({
            "status": "paused_safe",
            "reason": PAUSE_PATH.read_text(encoding="utf-8", errors="replace")[:500],
            "finished_at": _now(),
        })
        _write(STATE_PATH, state)
        print("SUPERVISOR paused_safe | manual_actions=0")
        return
    if not state["dependencies"]["healthy"]:
        state.update({"status": "failed_closed", "reason": "dependency_or_disk_health"})
        state["finished_at"] = _now()
        _write(STATE_PATH, state)
        raise SystemExit("Supervisor failed closed: dependency or disk health")
    try:
        from src.config import Config
        from src.control_backup import create_daily_snapshot
        cfg = Config("config.story.yaml")
        backup = create_daily_snapshot(int(cfg.get(
            "autopilot", "control_backup_retention_days", default=30,
        )))
        state["backup"] = {
            "status": backup.get("status"), "created_at": backup.get("created_at"),
            "path": backup.get("path"), "sha256": backup.get("sha256"),
            "off_device_copy": backup.get("off_device_copy", False),
        }
        result = run_controller(args)
        state["controller"] = {
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        }
        autopilot = _read(AUTOPILOT_STATE)
        inventory = _read(INVENTORY_PATH)
        state["autopilot"] = {
            "run_id": autopilot.get("run_id"), "status": autopilot.get("status"),
            "started_at": autopilot.get("started_at"), "finished_at": autopilot.get("finished_at"),
            "recovery": autopilot.get("recovery"),
        }
        state["inventory"] = {
            "target_ready_shorts": inventory.get("target_ready_shorts"),
            "ready_or_scheduled_count": inventory.get("ready_or_scheduled_count"),
            "shortage": inventory.get("shortage"),
        }
        state["production_queue"] = queue_summary(PRODUCTION_QUEUE)
        state["creative_queue"] = queue_summary(CREATIVE_QUEUE)
        run_status = str(autopilot.get("status") or "")
        if result.returncode != 0 or run_status in {
            "failed_closed", "failed", "release_integrity_blocked",
        }:
            state["status"] = "recovery_required"
            state["recovery"] = autopilot.get("recovery") or "controller exit " + str(result.returncode)
        elif run_status == "cooldown":
            state["status"] = "cooldown"
            state["recovery"] = autopilot.get("recovery") or "deferred items in cooldown; auto-repair pending"
        elif inventory.get("shortage"):
            state["status"] = "building_buffer"
            state["recovery"] = "continue automated production queue"
        else:
            state["status"] = "healthy"
            state["recovery"] = "none"
    except subprocess.TimeoutExpired:
        state["status"] = "recovery_required"
        state["recovery"] = "controller timeout; next bounded run resumes from persisted state"
    finally:
        state["finished_at"] = _now()
        _write(STATE_PATH, state)
    print(
        f"SUPERVISOR {state['status']} | ready={state.get('inventory', {}).get('ready_or_scheduled_count', 0)} "
        f"shortage={state.get('inventory', {}).get('shortage', 0)} | manual_actions=0"
    )
    if state["status"] == "recovery_required":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
